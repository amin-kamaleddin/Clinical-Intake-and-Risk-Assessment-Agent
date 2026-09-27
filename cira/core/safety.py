from __future__ import annotations

import re


SAFETY_REPLY = (
    "Thank you for telling me. Your immediate safety is important. "
    "Please call or text 988, or go to the nearest emergency department "
    "if you may be in immediate danger. We can continue the intake when it is safe to do so."
)


# These patterns are intentionally narrow. They require a first-person,
# present-tense statement that clearly expresses current risk.
_CURRENT_FIRST_PERSON_PATTERNS = [
    # English
    r"\bi(?:\s+am|'m)\s+(?:currently\s+)?(?:thinking about|considering)\s+(?:suicide|killing myself|hurting myself)\b",
    r"\bi\s+(?:currently\s+)?want\s+to\s+(?:die|kill myself|hurt myself|end my life)\b",
    r"\bi\s+(?:currently\s+)?(?:plan|intend)\s+to\s+(?:kill myself|hurt myself|end my life|hurt someone|kill someone)\b",
    r"\bi(?:\s+am|'m)\s+(?:currently\s+)?afraid\s+i\s+(?:may|might|will)\s+(?:hurt|kill)\s+(?:myself|someone)\b",
    r"\bi\s+(?:may|might|will)\s+(?:hurt|kill)\s+(?:myself|someone)\s+(?:today|tonight|now|soon)\b",
    r"\bi\s+(?:feel|think)\s+i\s+would\s+be\s+better\s+off\s+dead\b",
    r"\bi\s+(?:sometimes\s+|still\s+sometimes\s+)?(?:feel|think)\s+(?:that\s+)?i\s+would\s+be\s+better\s+off\s+dead\b",
    r"\bi\s+(?:sometimes\s+|currently\s+)?wish\s+i\s+(?:were|was)\s+dead\b",
    r"\bi\s+(?:sometimes\s+)?wish\s+to\s+die\b",
    r"\bi\s+(?:do not|don't)\s+want\s+to\s+be\s+alive\b",
    r"\bi\s+(?:feel|think)\s+there\s+is\s+no\s+reason\s+to\s+live\b",

    # Direct statements of current risk. These were absent, so "I am not safe
    # right now" and "I am suicidal" fell through the deterministic gate
    # entirely and depended on the model choosing to call raise_safety_flag.
    # Negation is handled by requiring the words to be adjacent: "i am not
    # suicidal" cannot match r"i am suicidal".
    r"\bi(?:\s+am|'m)\s+(?:currently\s+|actively\s+)?suicidal\b",
    r"\bi\s+feel\s+(?:currently\s+)?suicidal\b",
    r"\bi(?:\s+am|'m)\s+feeling\s+(?:currently\s+)?suicidal\b",
    r"\bi(?:\s+am|'m)\s+not\s+safe\b",
    r"\bi\s+(?:can'?t|cannot|am unable to)\s+(?:keep|stay|remain|feel)\s+(?:myself\s+)?safe\b",
    r"\bi\s+(?:do not|don't)\s+(?:feel|think i am)\s+safe\b",
    r"\bi\s+(?:have|'ve\s+got)\s+(?:current\s+|active\s+)?"
    r"(?:suicidal\s+thoughts|thoughts\s+of\s+(?:suicide|killing myself|hurting myself))\b",
    r"\bi(?:\s+am|'m)\s+having\s+(?:current\s+|active\s+)?"
    r"(?:suicidal\s+thoughts|thoughts\s+of\s+(?:suicide|killing myself|hurting myself))\b",
    r"\bi\s+(?:have|'ve got)\s+(?:a\s+)?plan\s+(?:and\s+intent\s+)?"
    r"(?:to\s+)?(?:kill|hurt|end)\b",
    r"\bi(?:\s+am|'m)\s+going\s+to\s+(?:kill|hurt)\s+myself\b",
    r"\bi(?:\s+am|'m)\s+going\s+to\s+end\s+my\s+life\b",
    r"\bi\s+mean\s+to\s+(?:do it|kill myself|end my life)\b",
    r"\bi\s+(?:want|need)\s+to\s+end\s+it\s+all\b",

    # French
    r"\bje\s+(?:pense|songe)\s+(?:actuellement\s+)?(?:au suicide|à me suicider|à me faire du mal)\b",
    r"\bje\s+veux\s+(?:mourir|me suicider|me faire du mal)\b",
    r"\bj['’]ai\s+(?:l['’]intention|un plan)\s+de\s+(?:me suicider|me faire du mal|faire du mal à quelqu['’]un)\b",

    # Hindi / Romanized Hindi — high-precision first-person phrases
    r"\bmain\s+(?:abhi\s+)?(?:marna|khud ko marna)\s+chahta\s+hoon\b",
    r"\bmain\s+(?:abhi\s+)?atmahatya\s+ke\s+baare\s+mein\s+soch\s+raha\s+hoon\b",
    r"मैं\s+(?:अभी\s+)?(?:मरना|खुद को मारना)\s+चाहता\s+हूँ",
    r"मैं\s+(?:अभी\s+)?आत्महत्या\s+के\s+बारे\s+में\s+सोच\s+रहा\s+हूँ",
]

# (compiled below, after the non-English patterns are appended)


# Strong indicators that a statement is not describing current patient risk.
# These are checked before positive patterns as an additional safeguard.
_NON_CURRENT_OR_NON_PATIENT_PATTERNS = [
    # Clear denial
    r"\b(?:i am not|i'm not|i do not|i don't|never)\s+(?:suicidal|thinking about suicide|thinking of suicide|going to hurt myself)\b",
    r"\bi\s+(?:have|had)\s+never\s+(?:wanted|tried|thought)\b.{0,40}\b(?:die|suicide|hurt myself|kill myself)\b",

    # Historical framing
    r"\b(?:years?|months?|weeks?|days?)\s+ago\b",
    r"\b(?:in the past|previously|when i was younger|used to)\b",

    # Third-person or family-history framing
    r"\b(?:my|his|her|their)\s+(?:mother|father|parent|brother|sister|uncle|aunt|son|daughter|friend|partner|spouse|relative|family member)\b.{0,60}\b(?:suicide|suicidal|self[- ]harm|killed himself|killed herself|died by suicide)\b",
    r"\b(?:he|she|they|my friend|my relative|my family member)\b.{0,40}\b(?:is|was|were|has been|had been)\b.{0,30}\b(?:suicidal|thinking about suicide|self[- ]harming)\b",

    # Hypothetical or quoted discussion
    r"\b(?:hypothetically|for example|what if someone|if a person|the question asks)\b",
]

# ── Non-English patterns ──────────────────────────────────────────────────────
#
# Added for the multilingual evaluation. Kept SEPARATE from the English list so
# the 46 English checks stay pinned to patterns nobody has edited.
#
# Two properties of these scripts break a naive substring pattern, and both are
# pinned by tests/test_safety_gate_multilingual.py:
#
#   NEGATION IS A PREFIX, not a separate word.
#       Farsi    دارم      ("I have")     is inside  ندارم      ("I do NOT have")
#       Farsi    می‌خواهم  ("I want")     is inside  نمی‌خواهم  ("I do NOT want")
#       Chinese  有        ("have")       is inside  没有        ("do not have")
#   A pattern matching the bare affirmative therefore fires on the negative. The
#   Farsi patterns use a (?<!ن) lookbehind; the Chinese ones pin the first-person
#   pronoun directly against the verb so an intervening 没 or 不 breaks the match.
#
#   LETTER FORMS VARY.
#       Arabic and Persian ی/ي and ک/ك are visually identical and both appear in
#   model output, so every occurrence is written as a character class. Persian
#   also inserts a zero-width non-joiner (U+200C) inside compound verbs, which is
#   matched as optional whitespace.
#
# No \b anywhere in the Chinese patterns: Chinese is written without spaces, so
# there are no word boundaries for \b to find.

# Up to four characters between a Chinese pronoun and its verb, none of which
# may be a negator and none of which may cross a clause boundary. Chinese has no
# spaces, so this is what stands in for "the same clause, a few words apart".
_ZH_GAP = r"(?:(?![\u4e0d\u6ca1\u522b\u83ab])[^\uff0c\u3002\uff01\uff1f\uff1b]){0,4}"

_ZWNJ = r"[\s\u200c]*"          # Persian compound-verb joiner, or a space
_YA = r"[\u064a\u06cc]"        # Arabic ya / Persian ye
_KA = r"[\u0643\u06a9]"        # Arabic kaf / Persian keheh

_CURRENT_FIRST_PERSON_PATTERNS += [
    # ── Mandarin Chinese ──
    # First person pinned against the verb: 我不想死 and 我没有自杀的想法 cannot
    # match, because 不 and 没 sit between the pronoun and the verb.
    # _ZH_GAP allows the adverbs Chinese puts between pronoun and verb
    # ("我现在也想死" - I now also want to die) while REFUSING to cross a
    # negator, so 我不想死 and 我没有自杀的想法 still cannot match.
    r"我" + _ZH_GAP + r"想死",
    r"我" + _ZH_GAP + r"想自[杀殺]",
    r"我" + _ZH_GAP + r"想[伤傷]害自己",
    r"我" + _ZH_GAP + r"要自[杀殺]",
    r"我" + _ZH_GAP + r"打算自[杀殺]",
    r"我" + _ZH_GAP + r"有自[杀殺]的想法",
    r"我现在不安全",
    r"我現在不安全",
    r"我不想活了",
    r"我活不下去了",

    # ── Arabic ──
    # Negation in Arabic is a separate preceding word (لا / ليس), so it is handled
    # by the exclusions below rather than by a lookbehind.
    r"أر" + _YA + r"د أن أموت",
    r"أر" + _YA + r"د أن أقتل نفس" + _YA,
    r"أر" + _YA + r"د أن أؤذ" + _YA + r" نفس" + _YA,
    r"لد" + _YA + r"\s+أفكار انتحار" + _YA + r"ة",
    r"أفكر ف" + _YA + r"\s+الانتحار",
    r"أنا لست بأمان",
    r"لا أشعر بالأمان",

    # ── Farsi ──
    # (?<!ن) is what keeps these off the negated forms.
    r"(?<!ن)م" + _YA + _ZWNJ + r"خواهم" + _ZWNJ + r"بم" + _YA + r"رم",
    r"(?<!ن)م" + _YA + _ZWNJ + r"خواهم.{0,20}بکشم",
    r"(?<!ن)م" + _YA + _ZWNJ + r"خواهم.{0,20}آس" + _YA + r"ب بزنم",
    r"خودکش" + _YA + r".{0,12}(?<!ن)دارم",
    r"به خودکش" + _YA + _ZWNJ + r"فکر م" + _YA + _ZWNJ + r"کنم",
    r"من در امان ن" + _YA + r"ستم",
]

_NON_CURRENT_OR_NON_PATIENT_PATTERNS += [
    # ── Mandarin Chinese: third person and historical ──
    r"(?:我的?)?(?:叔叔|伯伯|舅舅|姑姑|阿姨|父亲|母亲|爸爸|妈妈|哥哥|弟弟|姐姐|妹妹|朋友|亲戚|家人)"
    r".{0,12}(?:自杀|自殺|自残|自傷)",
    r"(?:他|她|他们|她们)(?:有|曾经有|想过).{0,10}(?:自杀|自殺)",
    r"我(?:以前|曾经|过去).{0,12}(?:自杀|自殺)",

    # ── Arabic: negation adjacent to the risk phrase, and third person ──
    r"ل" + _YA + r"س\s+لد" + _YA,
    r"لا أر" + _YA + r"د أن (?:أموت|أقتل|أؤذ)",
    r"(?:عم|خال|أخ|أخت|صد" + _YA + r"ق|والد|والدة|ابن|ابنة)"
    r"\w*\s*(?:\w+\s+){0,3}?(?:انتحر|لد" + _YA + r"ه|كان لد" + _YA + r"ه)",
    r"(?:أخ|عم|خال|صد" + _YA + r"ق)\w*\s+لد" + _YA + r"ه",

    # ── Farsi: third person and historical ──
    r"(?:عمو|دا" + _YA + r"|برادر|خواهر|پدر|مادر|دوست)\w*\s*(?:من\s*)?"
    r".{0,12}خودکش" + _YA,
    r"خودکش" + _YA + r".{0,12}(?:دارد|داشت|کرد)",
    r"(?:قبلاً|در گذشته|سابقاً).{0,20}خودکش" + _YA,
]



_COMPILED_CURRENT_PATTERNS = [
    re.compile(pattern, flags=re.IGNORECASE)
    for pattern in _CURRENT_FIRST_PERSON_PATTERNS
]

_COMPILED_EXCLUSIONS = [
    re.compile(pattern, flags=re.IGNORECASE)
    for pattern in _NON_CURRENT_OR_NON_PATIENT_PATTERNS
]


# Clause boundaries: sentence punctuation, and the conjunctions that join an
# unrelated historical statement to a current one.
_CLAUSE_SPLIT = re.compile(
    # Latin sentence punctuation, then the same for CJK and Arabic script:
    # 。！？，；  ، ؛ ؟ ۔ . English needs trailing whitespace to avoid splitting
    # "3.5 mg", but Chinese punctuation is unambiguous and is not followed by a
    # space, so it is matched without one.
    r"(?:[.!?;]+\s+)"
    r"|(?:[\u3002\uff01\uff1f\uff0c\uff1b\u060c\u061b\u061f\u06d4]+\s*)"
    # Coordinating conjunctions that join an unrelated historical or
    # third-person statement to a current one: English, then Arabic/Persian
    # وَ ("and") and که ("that").
    r"|(?:,?\s+\b(?:and|but|however|although|though|while)\b\s+)"
    r"|(?:\s+(?:\u0648|\u06a9\u0647)\s+)"
    # Arabic writes the conjunction و ATTACHED to the next word ("وأنا", not
    # "و أنا"), so a space-delimited split never fires and "my uncle died by
    # suicide AND I want to die" stayed one clause - suppressed entirely by the
    # family-history exclusion that matched its first half. Split at the space
    # before a و- prefixed word that begins a first-person form (أنا, أريد,
    # أفكر: all start with أ).
    r"|(?:\s+(?=\u0648\u0623))",
    flags=re.IGNORECASE,
)


def _split_clauses(text: str) -> list[str]:
    """Split a message into independently assessable clauses."""
    parts = [part.strip() for part in _CLAUSE_SPLIT.split(text)]
    return [part for part in parts if part]


def explicit_safety_trigger(text: str) -> bool:
    """Return ``True`` only for clear current first-person safety risk.

    This function is intentionally conservative. It must not trigger merely
    because a safety-related word appears. PHQ-9 question 9 should be handled
    separately from its saved numeric score: any score greater than zero raises
    the safety flag.
    """
    if not isinstance(text, str):
        return False

    normalized_text = " ".join(text.strip().split())
    if not normalized_text:
        return False

    # Evaluate CLAUSE BY CLAUSE, not over the whole message.
    #
    # Applying the exclusions to the entire message first meant one historical
    # or third-person phrase suppressed a current disclosure sitting beside it:
    # "My brother died by suicide and I currently want to die" was silently
    # dropped, because the family-history exclusion matched the first half.
    # A false negative here is the worst outcome the system can produce.
    #
    # Each clause is judged on its own. If ANY clause states current
    # first-person risk and is not itself excluded, the gate fires. Whole-message
    # evaluation is kept as an additional path so nothing that previously
    # triggered can stop triggering.
    for clause in _split_clauses(normalized_text):
        if any(p.search(clause) for p in _COMPILED_EXCLUSIONS):
            continue
        if any(p.search(clause) for p in _COMPILED_CURRENT_PATTERNS):
            return True

    if any(pattern.search(normalized_text) for pattern in _COMPILED_EXCLUSIONS):
        return False

    return any(
        pattern.search(normalized_text)
        for pattern in _COMPILED_CURRENT_PATTERNS
    )
