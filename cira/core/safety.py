"""Deterministic safety detection utilities."""


SAFETY_REPLY = (
    "I'm really glad you shared that with me. "
    "You are not alone. Please call 988 or go to your nearest emergency room. "
    "A member of our care team has been notified. "
    "Whenever you're ready, we can continue with the intake."
)


EXPLICIT_SAFETY_TERMS = [
    # English
    "suicide",
    "kill myself",
    "hurt myself",
    "self harm",
    "self-harm",
    "end my life",
    "hurt someone",
    "kill someone",

    # French
    "me suicider",
    "suicide",
    "envie de mourir",
    "mettre fin à mes jours",
    "me faire du mal",
    "faire du mal à quelqu'un",

    # Hindi / Romanized Hindi
    "आत्महत्या",
    "खुद को मार",
    "मर जाना चाहता",
    "mar jana chahta",
    "khud ko marna",
    "atmahatya",
]


def explicit_safety_trigger(text: str) -> bool:
    """Return True if the text contains an explicit crisis phrase."""
    if not isinstance(text, str):
        return False

    normalized_text = text.lower().strip()
    if not normalized_text:
        return False

    return any(
        term.lower() in normalized_text
        for term in EXPLICIT_SAFETY_TERMS
    )
