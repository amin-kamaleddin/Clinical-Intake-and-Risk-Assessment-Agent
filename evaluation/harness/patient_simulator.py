import json
import random
import re
import sys

from harness import config
from harness import personas as personas_module


def normalize_question(text: str) -> str:
    """Collapse whitespace and case so a re-ask is recognised as the same question."""
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()



ITEM_SIGNATURES: dict[str, tuple[tuple[str, ...], ...]] = {
    "phq9_q1": (("little interest", "pleasure in doing"),),
    "phq9_q2": (("down, depressed", "depressed, or hopeless", "hopeless"),),
    "phq9_q3": (("falling or staying asleep", "sleeping too much", "trouble sleeping"),),
    "phq9_q4": (("tired or having little energy", "little energy"),),
    "phq9_q5": (("poor appetite", "overeating"),),
    "phq9_q6": (("bad about yourself", "you are a failure", "let yourself or your family down"),),
    "phq9_q7": (("trouble concentrating", "concentrating on things"),),
    "phq9_q8": (("moving or speaking so slowly", "fidgety or restless"),),
    "phq9_q9": (("better off dead", "hurting yourself in some way"),),
    "gad7_q1": (("nervous, anxious", "anxious, or on edge", "on edge"),),
    "gad7_q2": (("stop or control worrying", "control worrying"),),
    "gad7_q3": (("worrying too much about different things",),),
    "gad7_q4": (("trouble relaxing", "difficulty relaxing"),),
    "gad7_q5": (("hard to sit still", "so restless that"),),
    "gad7_q6": (("easily annoyed", "annoyed or irritable"),),
    "gad7_q7": (("something awful might happen", "afraid as if", "afraid, as if"),),
}

DIFFICULTY_SIGNATURES = {
    "phq9": ("phq-9", "phq9"),
    "gad7": ("gad-7", "gad7"),
}


#: Arabic-Indic (٠-٩) and Persian/Urdu (۰-۹) digits, mapped to ASCII.
#: Arabic and Farsi intakes number items in their own numerals, and an item
#: labelled "GAD-7 السؤال ٣" carries no ASCII digit for the matcher to find.
_DIGIT_TRANSLATION = str.maketrans(
    "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669"
    "\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9",
    "01234567890123456789",
)


def _normalize_digits(text: str) -> str:
    """Rewrite non-ASCII numerals as ASCII so one matcher serves every script."""
    return str(text or "").translate(_DIGIT_TRANSLATION)


def identify_item_by_text(question: str) -> str | None:
    """Resolve a questionnaire item from its wording alone.

    Returns the item key (e.g. ``"phq9_q5"``) when exactly one signature
    matches. Ambiguity returns None rather than guessing: a wrong item is worse
    than falling through to the other resolution paths.
    """
    lowered = " ".join(str(question or "").lower().split())
    matches = [
        key for key, groups in ITEM_SIGNATURES.items()
        if any(any(phrase in lowered for phrase in group) for group in groups)
    ]
    return matches[0] if len(matches) == 1 else None


def _load_languages():
    """The shared language registry, imported through cira/ like everything else."""
    import sys
    cira_root = str(config.CIRA_DIR)
    if cira_root not in sys.path:
        sys.path.insert(0, cira_root)
    from core.languages import LANGUAGES as registry
    return registry


LANGUAGES = _load_languages()


def _language():
    """The active conversation language, from the shared registry.

    Imported lazily and through cira/, so the simulator and the agent read the
    SAME table. Two copies of these phrases would drift, and a drift means CIRA
    rejects a correctly answered item as "no option selected" - which looks like
    a comprehension failure in the transcript but is really bookkeeping.
    """
    import sys
    cira_root = str(config.CIRA_DIR)
    if cira_root not in sys.path:
        sys.path.insert(0, cira_root)
    from core.languages import get
    return get(config.LANGUAGE)


def score_to_response(score: int) -> str:
    """The printed option a patient says out loud for this score."""
    return _language().frequency_phrases[int(score)]


def item_is_being_administered(question: str) -> bool:
    """Whether this message actually puts a questionnaire item to the patient.

    Shared by the simulator (which warns and counts) and by
    tools/compare_languages (which reclassifies what was counted), so the two can
    never disagree about what a fall-through is.
    """
    text = _normalize_digits(str(question or ""))
    lowered = text.lower()
    if not re.search(r"phq[\s-]?9|gad[\s-]?7", lowered):
        return False
    # An item number directly after the instrument name.
    if re.search(r"(?:phq[\s-]?9|gad[\s-]?7)[^0-9]{0,16}?[1-9](?![0-9])", lowered):
        return True
    # Or the response scale, in any language: two frequency options, or two
    # difficulty options. Presenting the scale IS asking the item.
    for language in LANGUAGES.values():
        if sum(1 for p in language.frequency_phrases if p.lower() in lowered) >= 2:
            return True
    return _offers_difficulty_options(text)


def _offers_difficulty_options(question: str) -> bool:
    """True when the message presents the functional-difficulty scale.

    Requires TWO of the four options, so a single word shared with ordinary prose
    cannot trigger it. Checked across every language rather than only the active
    one, because a re-ask can arrive before the language is known.
    """
    text = str(question or "")
    for language in LANGUAGES.values():
        hits = sum(1 for phrase in language.difficulty_phrases if phrase in text)
        if hits >= 2:
            return True
    return False


def difficulty_to_response(value) -> str:
    """Translate a stored difficulty answer into the conversation language.

    patient_facts holds the English option ("Somewhat difficult") because that is
    the ground truth the record is scored against, so without this the patient
    answered the functional-difficulty item in English in the middle of an
    otherwise Mandarin interview.

    Mapped by POSITION on the scale rather than by translating the words, so the
    severity a scenario specified is the severity the patient reports. An
    unrecognised value is passed through unchanged rather than guessed at: a
    wrong option here silently changes what the scenario says.
    """
    text = str(value or "").strip()
    english = [phrase.lower() for phrase in ENGLISH_DIFFICULTY]
    try:
        index = english.index(text.lower())
    except ValueError:
        return text
    return _language().difficulty_phrases[index]


#: The English functional-difficulty scale, in ascending severity. Used to find
#: a stored answer's POSITION so it can be re-expressed in another language.
ENGLISH_DIFFICULTY = (
    "Not difficult at all",
    "Somewhat difficult",
    "Very difficult",
    "Extremely difficult",
)

#: English phrases, kept for the English path and for tests that assert them.
SCORE_TO_RESPONSE = {
    0: "Not at all",
    1: "Several days",
    2: "More than half the days",
    3: "Nearly every day",
}


class PatientSimulator:
    """Simulate one patient consistently across a complete CIRA intake."""

    def __init__(self, scenario: dict, persona=None, seed: int | None = None,
                 repetition: int = 0):
        """Parameters
        ----------
        scenario
            A single entry from ``cira_scenarios.json``.
        persona
            A ``Persona``, a persona id, or ``None`` for the default ``clear``
            persona (which reproduces the pre-persona behaviour).
        seed
            Base seed for this patient's stochastic behaviour. Defaults to
            ``config.PERSONA_SEED``. Combined with the case id and persona id,
            so two cases sharing a persona still behave differently.
        """
        from langchain_openai import ChatOpenAI

        self.scenario = scenario
        self.persona = personas_module.get_persona(persona)

        # A pinned CIRA_EVAL_TEMPERATURE wins, so the persona's effect can be
        # isolated to its prompt when you want that comparison.
        self.temperature = (
            config.PATIENT_TEMPERATURE
            if config.PATIENT_TEMPERATURE_IS_PINNED
            else self.persona.temperature
        )

        self.model = ChatOpenAI(
            model=config.PATIENT_MODEL_NAME,
            temperature=self.temperature,
            base_url=config.OPENROUTER_BASE_URL,
            api_key=config.OPENROUTER_API_KEY,
        )

        # The repetition index enters the seed so each repetition is a genuinely
        # independent realisation - otherwise every repetition would reproduce
        # the same deferral and hedge pattern and the variance would collapse.
        #
        # It is the ONLY thing that varies: the same (case, repetition) gives the
        # same patient for cira, rule_based and naive_llm, so comparisons stay
        # paired and the paired bootstrap is valid.
        base_seed = config.PERSONA_SEED if seed is None else seed
        self.repetition = repetition
        self._rng = random.Random(
            f"cira-patient::{base_seed}::{scenario.get('case_id')}"
            f"::{self.persona.id}::rep{repetition}"
        )

        # Deferral bookkeeping, reported afterwards via ``behaviour_summary()``.
        self._deflections_by_item: dict[str, int] = {}
        self._deflections_by_instrument: dict[str, int] = {}
        self._deflection_log: list[dict] = []

        # Free-text hedging. Persona behaviour in a free-text answer otherwise
        # depends entirely on the model obeying a prompt, which it does
        # unevenly; this makes a bounded amount of it deterministic.
        self._hedges_used = 0
        self._hedged_last_turn = False
        self._hedges_this_section = 0
        self._hedges_by_section: dict[str, int] = {}
        self._current_section = "(none)"
        self._hedged_questions: set[str] = set()

        # The last instrument CIRA named. CIRA's questionnaire prompts tell it
        # to number items as "Question 1:", which carries no instrument name, so
        # the patterns below cannot tell PHQ-9 item 3 from GAD-7 item 3. Without
        # this the item falls through to the LLM and the patient improvises an
        # answer off the fixed scale, silently corrupting the totals that
        # structured_score treats as ground truth.
        self._current_instrument: str | None = None
        # The specific item last asked. CIRA re-asks and clarifications often
        # drop the item label ("Thinking about the last two weeks overall, was
        # poor appetite or overeating present: 0 - Not at all ..."), which used
        # to lose the deterministic path entirely: the item fell through to the
        # LLM, the patient improvised an answer off the fixed scale, and the
        # instrument total was silently corrupted. Latching the item means a
        # re-ask still resolves to the same stored score.
        self._current_item: str | None = None
        #: Items that could not be resolved deterministically. See answer().
        self._questionnaire_fall_throughs = 0
        self._fall_through_log: list = []

        self.history = []
        self.system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        patient_facts = json.dumps(
            self.scenario["patient_facts"],
            indent=2,
            ensure_ascii=False,
        )
        disclosure_plan = json.dumps(
            self.scenario.get("multi_turn_disclosure_plan", {}),
            indent=2,
            ensure_ascii=False,
        )
        safety_profile = json.dumps(
            self.scenario.get("safety_profile", {}),
            indent=2,
            ensure_ascii=False,
        )

        return f"""
You are acting as a patient during an automated evaluation of CIRA,
a clinical intake agent.

GENERAL RULES
1. Address CIRA's latest question. How directly you address it is governed by
   your COMMUNICATION STYLE below, which overrides this rule.
2. Use only the supplied patient facts and plans.
3. Never invent information.
4. Answer naturally.
5. Do not reveal the full history at once.
6. Never mention being an AI, simulator, evaluation, hidden label, or test case.
7. Remain consistent throughout the conversation.
8. If a fact is null or unknown, say that you do not know or have nothing to report.
9. Do not calculate or disclose PHQ-9 or GAD-7 totals.
10. Never mention or hint at your communication style; simply speak that way.

MULTI-ENTRY RULES
1. For medications and other repeatable information, reveal one entry at a time.
2. Give missing details for the current entry when CIRA asks.
3. Reveal the next entry only when CIRA asks whether there are any others.
4. After the final entry, clearly say: "{_language().no_more_entries}"
5. Do not repeat an entry already disclosed.
6. If CIRA explicitly asks for all entries together, you may list all supplied entries.
7. Never invent a dose, frequency, start date, duration, or stopping reason.

QUESTIONNAIRE RULES
Use exactly:
{self._scale_block()}

Patient description:
{self.scenario.get("patient_simulator_instructions", "")}

Safety profile:
{safety_profile}

Gradual disclosure plan:
{disclosure_plan}

Patient facts:
{patient_facts}

{self._persona_precedence_block()}

{self._language_block()}
""".strip()

    def _language_block(self) -> str:
        """Tell the patient which language to speak, or say nothing for English.

        The patient must speak the SAME language CIRA is using, or the transcript
        is a code-switching artefact and the flow judge scores that instead of
        the intake. Facts stay bound to patient_facts either way: this changes
        only the language they are said in, never their content.
        """
        language = _language()
        if language.name == "English":
            return ""
        return f"""LANGUAGE - THIS SECTION OVERRIDES EVERYTHING ABOVE
Speak {language.name} ({language.native_name}) for the ENTIRE conversation.
- The patient description and the rules above are written in English and quote
  English phrases. Those are the MEANINGS to convey, not the words to say. Where
  anything above tells you to say a specific English phrase, say its
  {language.name} equivalent instead.
- In particular: when you have disclosed every entry and are asked whether there
  are more, say "{language.no_more_entries}" - NOT the English wording quoted
  above.
- Reply in {language.name} even though the facts below are written in English.
- Translate the facts faithfully. Never add, drop or soften a detail in
  translation, and never invent one that is not listed.
- Numbers, medication names and dates stay recognisable: give a medication by
  the name written below, transliterated if that is normal in {language.name}.
- Say questionnaire answers using the exact printed option listed under
  QUESTIONNAIRE RULES below, in {language.name}."""

    def _scale_block(self) -> str:
        """The four printed frequency options, in the conversation language."""
        phrases = _language().frequency_phrases
        return "\n".join(f"{score} = {phrase}" for score, phrase in enumerate(phrases))

    def _persona_precedence_block(self) -> str:
        """The persona block, placed LAST and declared to win on conflicts.

        It used to sit in the middle, ahead of ~4,000 characters of scenario
        instructions telling the patient to answer only what was asked, briefly
        and precisely. Those came later and were far more specific, so they won:
        a "confused" twelve-year-old was reciting a correctly formatted address
        and a doctor's name in capitals. Position and an explicit precedence
        note are what make the persona actually take effect.
        """
        return f"""
{self.persona.behaviour_block}

PRECEDENCE
The COMMUNICATION STYLE above governs HOW you speak and overrides any earlier
instruction to answer briefly, precisely, directly, or only the latest question.
It does NOT override the facts: everything you say must still come from the
patient facts, and you must never state a concrete detail that contradicts them.
Style is yours to control; content is not.
""".strip()

    @staticmethod
    def _instrument_regex(instrument: str) -> str:
        """Flexible pattern for an instrument name.

        ``instrument`` arrives as a compact key like "phq9"/"gad7", but CIRA
        writes "PHQ-9", "PHQ 9", or "phq9". Insert an optional separator before
        the trailing digit so all spellings match.
        """
        letters = instrument[:-1]
        digit = instrument[-1]
        return rf"{letters}[\s-]?{digit}"

    @classmethod
    def _question_number(cls, question: str, instrument: str, max_question: int) -> int | None:
        """Extract a questionnaire item number from common CIRA wording."""
        lower = _normalize_digits(question.lower())
        inst = cls._instrument_regex(instrument)

        patterns = [
            # "PHQ-9 question 3", "phq 9 item 3", "phq9 q3", "phq 9 number 3",
            # "phq-9 #3", "phq-9 3"
            rf"{inst}[\s-]*(?:question|item|number|no\.?|#|q)?\s*([1-{max_question}])\b",
            # "question 3 of 9", "question 3 / 9"
            rf"question\s*([1-{max_question}])\s*(?:of|/)\s*{max_question}\b",
            # bare "q3"
            rf"\bq\s*([1-{max_question}])\b",
            # explicit key "phq9_q3" / "phq-9_q3"
            rf"{inst}_q([1-{max_question}])\b",
            # LANGUAGE-AGNOSTIC fallback, tried last so the specific patterns win.
            #
            # The word for "question" gets translated even when the instrument
            # name does not: CIRA wrote "**PHQ-9 Question 1:**" but
            # "GAD-7 问题 1：" in the same Mandarin intake. The optional
            # (?:question|item|...) group above cannot skip 问题, so all seven
            # GAD-7 items fell through to the LLM and their ground-truth answers
            # were lost while all nine PHQ-9 items resolved.
            #
            # The instrument name and the digit stay stable in every language, so
            # anything non-numeric between them is allowed. Bounded and non-greedy
            # so it takes the item number rather than some later digit.
            rf"{inst}[^0-9]{{0,16}}?([1-{max_question}])(?![0-9])",
        ]
        for pattern in patterns:
            match = re.search(pattern, lower)
            if match:
                return int(match.group(1))

        return None

    def _track_instrument(self, question: str) -> None:
        """Latch onto the most recent explicit PHQ-9 / GAD-7 mention."""
        lower = question.lower()
        if re.search(r"phq[\s-]?9", lower):
            self._current_instrument = "phq9"
        elif re.search(r"gad[\s-]?7", lower):
            self._current_instrument = "gad7"

    def _bare_question_number(self, question: str) -> int | None:
        """Item number from an unqualified "Question 3:" / "Question 3 of 9"."""
        match = re.search(
            r"\bquestion\s*#?\s*(\d{1,2})\b",
            _normalize_digits(question.lower()),
        )
        return int(match.group(1)) if match else None

    def _looks_like_scale_prompt(self, question: str) -> bool:
        """True when the message restates the response options.

        Used to recognise an unlabelled re-ask. Requiring two or more of the
        fixed phrases keeps ordinary conversation from being read as a
        questionnaire turn.
        """
        lower = question.lower()
        return sum(
            phrase in lower
            for phrase in personas_module.CANONICAL_RESPONSES
        ) >= 2

    def _answer_for(self, item_key: str) -> str:
        instrument = item_key.split("_", 1)[0]
        return self.scenario["patient_facts"][instrument][item_key]

    def _identify_questionnaire_item(self, question: str) -> tuple[str, str] | None:
        """Return ``(item_key, exact_response)`` for an identifiable item.

        The item key (e.g. ``"phq9_q3"``) is what lets deferral be counted per
        item rather than per turn, so re-asking the same item always converges.
        """
        # ORDER MATTERS. The item's own wording is checked FIRST, because it is
        # the only signal that cannot be fooled by a stray token elsewhere in
        # the message.
        #
        # The previous order tried PHQ-9 numbering first. One of the patterns
        # in _question_number is a bare r"\bq\s*([1-9])\b", so a message that
        # merely CONTAINED "q1" anywhere matched it - including the pending-field
        # hint the agent appends ("could you tell me about gad7 q1"). A question
        # that plainly said "**GAD-7 Question 1:**" therefore resolved to
        # phq9_q1, and the whole GAD-7 record came back as a copy of the PHQ-9
        # record. It only showed up in repetitions where deflections caused that
        # hint to be appended, which is why it was intermittent: 4 of 24 records.
        # Resolve by wording ONLY where a questionnaire is actually being
        # administered. The signatures are item TEXT - "trouble concentrating",
        # "feeling nervous, anxious, or on edge" - and an intake question that
        # offers examples of symptoms contains them verbatim:
        #
        #   "When school feels overwhelming, what happens - do you feel anxious
        #    or low, have trouble concentrating or sleeping, or miss classes?"
        #
        # Exactly one signature matched that, so the ambiguity guard below let
        # it through and the patient answered a free-text question about their
        # presenting problem with "More than half the days" - four times, until
        # the section hit the stall guard and was abandoned. CIRA lost
        # primary_problems and goals and was scored down for a simulator fault.
        #
        # The gate is the section, not the wording: _current_instrument is set
        # only inside phq9/gad7 (see begin_section), and a question naming the
        # instrument explicitly is admitted from anywhere.
        in_questionnaire = (
            self._current_instrument is not None
            or self._looks_like_questionnaire(question)
        )
        by_text = identify_item_by_text(question) if in_questionnaire else None
        if by_text is not None:
            self._current_item = by_text
            self._current_instrument = by_text.split("_", 1)[0]
            return by_text, score_to_response(self._answer_for(by_text))

        # Numbered lookup, CURRENT instrument first. Trying one instrument
        # unconditionally first lets a stray token from the other one win; the
        # section we are actually in should take precedence.
        instrument_order = (
            ["gad7", "phq9"] if self._current_instrument == "gad7"
            else ["phq9", "gad7"]
        )
        for instrument in instrument_order:
            limit = 9 if instrument == "phq9" else 7
            number = self._question_number(question, instrument, limit)
            if number is not None:
                key = f"{instrument}_q{number}"
                self._current_item = key
                self._current_instrument = instrument
                return key, score_to_response(self._answer_for(key))

        # Bare "Question N:" with no instrument named at all - resolve against
        # whichever instrument the current section administers.
        if self._current_instrument:
            limit = 9 if self._current_instrument == "phq9" else 7
            number = self._bare_question_number(question)
            if number is not None and 1 <= number <= limit:
                key = f"{self._current_instrument}_q{number}"
                self._current_item = key
                return key, score_to_response(self._answer_for(key))

        # The functional-difficulty item, which carries no number for the matcher
        # above to find. Requiring the English word "difficult" lost it entirely
        # outside English: CIRA wrote "PHQ-9 功能受影响程度" and "GAD-7 功能困难"
        # in the same run, so even one translated keyword would not have covered
        # both. The reliable signal is that the message OFFERS THE DIFFICULTY
        # OPTIONS rather than the 0-3 frequency scale, and those options are
        # canonical - the agent is instructed to use them verbatim.
        lower = question.lower()
        difficulty_asked = "difficult" in lower or _offers_difficulty_options(question)

        if ("phq-9" in lower or "phq9" in lower) and difficulty_asked:
            self._current_item = "phq9_difficulty"
            return "phq9_difficulty", difficulty_to_response(self._answer_for("phq9_difficulty"))

        if ("gad-7" in lower or "gad7" in lower) and difficulty_asked:
            self._current_item = "gad7_difficulty"
            return "gad7_difficulty", difficulty_to_response(self._answer_for("gad7_difficulty"))

        # Unlabelled re-ask: the message restates the response options but
        # carries no item label, so it is a clarification of the item already
        # in progress. Without this the item is handed to the LLM and the score
        # is invented.
        # The latched item is only usable if it belongs to the instrument the
        # current section administers. A stale item from the previous
        # questionnaire must never answer for this one.
        if (
            self._current_item
            and self._looks_like_scale_prompt(question)
            and (
                self._current_instrument is None
                or self._current_item.startswith(self._current_instrument)
            )
        ):
            key = self._current_item
            if key.endswith("_difficulty"):
                return key, self._answer_for(key)
            return key, score_to_response(self._answer_for(key))

        return None

    @staticmethod
    def _looks_like_questionnaire(question: str) -> bool:
        """True only when the message is ADMINISTERING an item, not mentioning one.

        Naming the instrument is not enough. CIRA says "PHQ-9 问卷已经完成，您的
        答案已记录" - the PHQ-9 is finished and your answers are recorded - which
        contains "PHQ-9" and asks nothing. Counting that as an item produced
        fall-through warnings on a questionnaire that had already completed
        correctly, which is the one diagnostic a non-English run is read on: a
        real fall-through means an answer was improvised instead of taken from
        ground truth, and inflating it with confirmations makes a clean run look
        corrupted.

        An item is the instrument name PLUS something to answer: a number, or the
        response scale.
        """
        return item_is_being_administered(question)

    # ------------------------------------------------------------------ #
    # Persona-driven deferral
    # ------------------------------------------------------------------ #
    @staticmethod
    def _instrument_of(item_key: str) -> str:
        """"phq9_q3" -> "phq9". Budgets are counted per instrument."""
        return item_key.split("_", 1)[0]

    #: Intake section -> questionnaire it administers.
    SECTION_INSTRUMENTS = {"phq9": "phq9", "gad7": "gad7"}

    def begin_section(self, section: str) -> None:
        """Start a new intake section: refresh the hedge budget AND the instrument.

        Latching the instrument here is what makes a bare "Question 1: ..."
        resolvable. A system that never writes the instrument name - the
        rule-based comparator does exactly this - previously left
        ``_current_instrument`` unset, so the item fell through to the free-text
        LLM and the patient invented an answer off the 0-3 scale.

        That was not hypothetical: on case 04-01 the rule-based arm received
        "Several days" for PHQ-9 item 5 whose ground truth is 0, and was scored
        as wrong for a simulator fault. The simulator must reproduce its own
        ground truth identically for every system, or arms are not comparable.

        ``_current_item`` is reset at the same time so a stale item from the
        previous instrument can never satisfy an unlabelled re-ask.
        """
        self._current_section = section
        self._hedges_this_section = 0
        self._current_instrument = self.SECTION_INSTRUMENTS.get(section)
        self._current_item = None

    def _should_hedge(self, question: str) -> bool:
        """Whether to stall on this free-text question rather than answer it.

        A given question is hedged at most once, so a re-ask always gets a real
        answer and no field can loop. The budget bounds total turn inflation.
        """
        persona = self.persona
        if persona.freetext_hedge_probability <= 0:
            return False
        if self._hedges_this_section >= persona.freetext_hedge_budget_per_section:
            return False
        if normalize_question(question) in self._hedged_questions:
            return False
        # Never hedge twice in a row. A question is only hedged once, but the
        # interviewer rephrases when stalled, and each rephrasing counted as a
        # new question - so the patient could stonewall one field across four
        # different wordings and the interviewer would give up. One hedge per
        # exchange keeps the persona hard while guaranteeing that a single good
        # follow-up always gets the real answer.
        if self._hedged_last_turn:
            return False
        return self._rng.random() < persona.freetext_hedge_probability

    HEDGE_DIRECTIVE = (
        "FOR THIS REPLY ONLY: do not give the concrete answer yet. Stall in a "
        "way that fits your communication style - hedge, give only part of it, "
        "wander off the point, mishear the question, or ask what they mean. Do "
        "not state the fact you are being asked for. If the interviewer asks "
        "again or breaks the question down, answer properly next time. Never "
        "say a detail that contradicts your facts."
    )

    def _should_deflect(self, item_key: str) -> bool:
        """Decide whether to stall on this questionnaire item.

        Three gates, all of which must pass. Together they guarantee the intake
        terminates: an item can be deferred at most ``max_deflections_per_item``
        times, and each instrument at most
        ``deflection_budget_per_instrument`` times.
        """
        persona = self.persona
        if persona.max_deflections_per_item <= 0 or not persona.deflection_lines:
            return False

        instrument = self._instrument_of(item_key)
        if (
            self._deflections_by_instrument.get(instrument, 0)
            >= persona.deflection_budget_per_instrument
        ):
            return False
        if self._deflections_by_item.get(item_key, 0) >= persona.max_deflections_per_item:
            return False
        return self._rng.random() < persona.questionnaire_deflection_probability

    def _deflection_line(self, item_key: str) -> str:
        # Outside English, draw from the language's pool instead of the persona's
        # English list. The persona still controls HOW OFTEN it deflects (its
        # probability and budgets); only the wording comes from the language.
        # English is untouched, so the frozen English run is unaffected.
        language = _language()
        pool = (
            language.deflection_lines
            if language.name != "English" and language.deflection_lines
            else self.persona.deflection_lines
        )
        line = self._rng.choice(pool)
        instrument = self._instrument_of(item_key)
        self._deflections_by_item[item_key] = self._deflections_by_item.get(item_key, 0) + 1
        self._deflections_by_instrument[instrument] = (
            self._deflections_by_instrument.get(instrument, 0) + 1
        )
        self._deflection_log.append({
            "item": item_key,
            "instrument": instrument,
            "attempt": self._deflections_by_item[item_key],
            "response": line,
        })
        return line

    def answer(self, cira_question: str) -> str:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        self._track_instrument(cira_question)
        identified = self._identify_questionnaire_item(cira_question)

        # Preserve both sides of the conversation in simulator memory.
        self.history.append(HumanMessage(content=cira_question))

        if identified is not None:
            item_key, exact_response = identified
            if self._should_deflect(item_key):
                patient_answer = self._deflection_line(item_key)
            else:
                patient_answer = exact_response
            # Questionnaire turns never count as a free-text hedge.
            self._hedged_last_turn = False
        else:
            # A question that references an instrument but produced no
            # deterministic answer means the item number could not be parsed;
            # the LLM may answer off the fixed frequency scale and corrupt the
            # PHQ-9/GAD-7 totals. Surface it rather than failing silently.
            # A questionnaire turn that reaches the LLM corrupts the very
            # totals structured_score treats as exact. Inside a questionnaire
            # section this is a harness fault, not a soft warning: raise, so it
            # is impossible to ship results built on invented scores.
            if self._current_instrument and self._looks_like_scale_prompt(cira_question):
                raise RuntimeError(
                    f"Questionnaire item could not be resolved deterministically "
                    f"in section {self._current_section!r}: {cira_question!r}. "
                    f"The item would have been answered by the free-text model, "
                    f"which invalidates the instrument total."
                )
            if self._looks_like_questionnaire(cira_question):
                # RECORDED, not only warned about. A fall-through means the item
                # did not use its stored ground-truth answer, so a structured
                # score computed over fall-throughs measures the simulator's
                # improvisation rather than the intake. The count has to survive
                # in the artifacts: reading it back off a console log means it is
                # gone the moment the log is rotated or deleted, and it is the
                # first number to check on any non-English run.
                self._questionnaire_fall_throughs += 1
                self._fall_through_log.append(cira_question[:200])
                print(
                    "[patient_simulator] WARNING: questionnaire item fell through "
                    f"to the LLM (no deterministic answer): {cira_question!r}",
                    file=sys.stderr,
                )
            messages = [
                SystemMessage(content=self.system_prompt),
                *self.history,
            ]
            hedging = self._should_hedge(cira_question)
            self._hedged_last_turn = hedging
            if hedging:
                self._hedges_used += 1
                self._hedges_this_section += 1
                self._hedges_by_section[self._current_section] = (
                    self._hedges_by_section.get(self._current_section, 0) + 1
                )
                self._hedged_questions.add(normalize_question(cira_question))
                messages.append(SystemMessage(content=self.HEDGE_DIRECTIVE))
            response = self.model.invoke(messages)
            patient_answer = response.content.strip()

        self.history.append(AIMessage(content=patient_answer))
        return patient_answer

    # ------------------------------------------------------------------ #
    # Reporting
    # ------------------------------------------------------------------ #
    def behaviour_summary(self) -> dict:
        """What the persona actually did, for stamping into artifacts.

        Deferral counts are the useful diagnostic: they say how much extra work
        the persona created, which separates "the system needed more turns
        because the patient stalled" from "it needed more turns because it
        looped".
        """
        return {
            "persona": self.persona.metadata(),
            "repetition": self.repetition,
            "temperature": self.temperature,
            "temperature_pinned": config.PATIENT_TEMPERATURE_IS_PINNED,
            "questionnaire_deflections": sum(self._deflections_by_item.values()),
            # Must be 0. Anything above it means that many items were answered by
            # the LLM instead of from ground truth.
            "questionnaire_fall_throughs": self._questionnaire_fall_throughs,
            "fall_through_questions": self._fall_through_log,
            "freetext_hedges": self._hedges_used,
            "max_consecutive_hedges": 1,
            "hedges_by_section": dict(self._hedges_by_section),
            "deflections_by_instrument": dict(self._deflections_by_instrument),
            "deflections_by_item": dict(self._deflections_by_item),
            "deflection_log": self._deflection_log,
        }