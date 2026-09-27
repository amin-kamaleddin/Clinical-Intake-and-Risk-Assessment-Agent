"""Per-language data the intake needs in order to run outside English.

ONE source of truth, deliberately. The patient simulator emits questionnaire
answers from this table and CIRA accepts them from the same table; if the two
ever held separate copies, a drift between them would silently stop scores being
recorded and the run would look like a comprehension failure instead of a
bookkeeping one.

What makes a non-English intake work at all is that three things stay
language-independent:

  * the questionnaire ITEM LABEL. CIRA is instructed to write
    "PHQ-9 Question 3: ..." verbatim - Latin instrument name, Arabic numeral -
    in every language, so the simulator resolves the item from the label and
    never has to match translated item text.
  * the RESPONSE DIGITS. Options are presented as "0 - ...", "1 - ..." in every
    language, so a patient answering with a number is understood everywhere.
  * the RECORD. CIRA stores every saved value in English whatever the
    conversation language (see prompts/static_prompt.py), so record scoring,
    the record judge and the structured score are untouched by translation.

Only the patient-facing wording changes, which is what this table holds.

TRANSLATION PROVENANCE: the frequency and difficulty phrases follow the
published PHQ-9 / GAD-7 translations for each language. They should still be
checked by a native speaker before the numbers go into a manuscript - a wording
that is understandable but not the official phrasing would change what the
instrument measures, and that is not something this file can verify.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Language:
    """Everything the intake needs to run in one language."""

    name: str                       # value used for state["preferred_language"]
    native_name: str
    #: PHQ-9 / GAD-7 frequency options, indexed by score 0-3.
    frequency_phrases: tuple
    #: Functional-difficulty options, in ascending severity.
    difficulty_phrases: tuple
    #: Question marks this script uses. Latin "?" is always accepted as well,
    #: because models mix scripts and the instrument labels stay Latin.
    question_marks: tuple = ("?",)
    #: How well the deterministic safety gate covers this language.
    #: "verified" - patterns exist AND are pinned by tests in this repo.
    #: "basic"    - a small high-precision set only; the gate WILL miss
    #:              phrasings it does not enumerate, and detection then falls to
    #:              the model and to the PHQ-9 Q9 rule.
    safety_coverage: str = "basic"
    #: Extra notes for the manuscript's limitations section.
    notes: str = ""


ENGLISH = Language(
    name="English",
    native_name="English",
    frequency_phrases=(
        "Not at all",
        "Several days",
        "More than half the days",
        "Nearly every day",
    ),
    difficulty_phrases=(
        "Not difficult at all",
        "Somewhat difficult",
        "Very difficult",
        "Extremely difficult",
    ),
    safety_coverage="verified",
)

FRENCH = Language(
    name="French",
    native_name="Français",
    frequency_phrases=(
        "Jamais",
        "Plusieurs jours",
        "Plus de la moitié du temps",
        "Presque tous les jours",
    ),
    difficulty_phrases=(
        "Pas du tout difficile",
        "Un peu difficile",
        "Très difficile",
        "Extrêmement difficile",
    ),
    safety_coverage="verified",
)

MANDARIN = Language(
    name="Mandarin Chinese",
    native_name="中文",
    frequency_phrases=(
        "完全不会",
        "有几天",
        "一半以上的天数",
        "几乎每天",
    ),
    difficulty_phrases=(
        "一点也不困难",
        "有些困难",
        "很困难",
        "极其困难",
    ),
    # Chinese uses a full-width question mark. A reply punctuated only with
    # U+FF1F is still a question, and reading it as a statement was what made
    # question detection fail outside English.
    question_marks=("？", "?"),
    notes="No inter-word spacing, so word-boundary regex (\\b) does not apply.",
)

ARABIC = Language(
    name="Arabic",
    native_name="العربية",
    frequency_phrases=(
        "أبداً",
        "عدة أيام",
        "أكثر من نصف الأيام",
        "تقريباً كل يوم",
    ),
    difficulty_phrases=(
        "ليس صعباً على الإطلاق",
        "صعب نوعاً ما",
        "صعب جداً",
        "صعب للغاية",
    ),
    question_marks=("؟", "?"),
    notes=(
        "Right-to-left. Optional diacritics mean the same word appears with and "
        "without vowel marks, so patterns must tolerate both."
    ),
)

HINDI = Language(
    name="Hindi",
    native_name="हिन्दी",
    frequency_phrases=(
        "बिल्कुल नहीं",
        "कई दिन",
        "आधे से ज़्यादा दिन",
        "लगभग हर दिन",
    ),
    difficulty_phrases=(
        "बिल्कुल कठिन नहीं",
        "कुछ कठिन",
        "बहुत कठिन",
        "अत्यंत कठिन",
    ),
    safety_coverage="verified",
    notes="Nukta variants (ज़/ज) appear interchangeably in model output.",
)

FARSI = Language(
    name="Farsi",
    native_name="فارسی",
    frequency_phrases=(
        "هیچ وقت",
        "چند روز",
        "بیشتر از نیمی از روزها",
        "تقریباً هر روز",
    ),
    difficulty_phrases=(
        "به هیچ وجه دشوار نبود",
        "تا حدی دشوار",
        "بسیار دشوار",
        "به شدت دشوار",
    ),
    question_marks=("؟", "?"),
    notes=(
        "Right-to-left. Arabic and Persian forms of the same letters (ی/ي, ک/ك) "
        "are visually similar and both occur in model output, so patterns must "
        "accept either."
    ),
)


LANGUAGES = {
    language.name: language
    for language in (ENGLISH, FRENCH, MANDARIN, ARABIC, HINDI, FARSI)
}

#: Languages the multilingual evaluation runs, English first as the control.
EVALUATION_LANGUAGES = [
    "English", "Mandarin Chinese", "French", "Arabic", "Hindi", "Farsi",
]


def get(name: str) -> Language:
    """Look up a language, falling back to English for anything unknown.

    Matches the prompt's own rule ("if the preferred language is unsupported,
    use English") so the harness and the agent cannot disagree about what an
    unrecognised name means.
    """
    return LANGUAGES.get(name, ENGLISH)


def all_frequency_phrases() -> tuple:
    """Every frequency phrase in every language, lowercased.

    CIRA's guard against recording an unselected score accepts a reply that
    contains one of these. It has to span all languages at once, because the
    guard runs without knowing which language the conversation is in.
    """
    return tuple(
        phrase.lower()
        for language in LANGUAGES.values()
        for phrase in language.frequency_phrases
    )


def all_question_marks() -> tuple:
    """Every question mark used by any supported language."""
    return tuple({mark for language in LANGUAGES.values() for mark in language.question_marks})
