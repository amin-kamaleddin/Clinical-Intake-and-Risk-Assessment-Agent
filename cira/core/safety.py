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

_COMPILED_CURRENT_PATTERNS = [
    re.compile(pattern, flags=re.IGNORECASE)
    for pattern in _CURRENT_FIRST_PERSON_PATTERNS
]


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

_COMPILED_EXCLUSIONS = [
    re.compile(pattern, flags=re.IGNORECASE)
    for pattern in _NON_CURRENT_OR_NON_PATIENT_PATTERNS
]


# Clause boundaries: sentence punctuation, and the conjunctions that join an
# unrelated historical statement to a current one.
_CLAUSE_SPLIT = re.compile(
    r"(?:[.!?;]+\s+)|(?:,?\s+\b(?:and|but|however|although|though|while)\b\s+)",
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
