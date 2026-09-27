"""Deterministic safety gate, outside English.

The gate is a high-precision backstop, not the sensitivity guarantee. That comes
from the PHQ-9 question 9 rule, which acts on the saved numeric score and is
therefore language-independent: a risk case is caught in every language once the
questionnaire is administered, whether or not this gate fires. What the gate adds
is EARLY detection, before the questionnaire is reached.

So a missing pattern costs detection latency, while a wrong pattern costs a false
alarm on a patient who is not at risk. The adversarial pairs below are the ones
that matter, because in these scripts a negation is often a PREFIX on the same
word rather than a separate one:

    Farsi    دارم  ("I have")  is a substring of  ندارم  ("I do NOT have")
    Chinese  有     ("have")    is a substring of  没有    ("do NOT have")
    Arabic   لدي   ("I have")  is negated by a preceding  ليس

A naive substring pattern fires on all three negatives. Every one is pinned
below.

Offline. No API keys, no network.
"""

from __future__ import annotations

import sys
import types

if "dotenv" not in sys.modules:
    _dotenv = types.ModuleType("dotenv")
    _dotenv.load_dotenv = lambda **kwargs: None
    sys.modules["dotenv"] = _dotenv

from core.safety import explicit_safety_trigger  # noqa: E402

# Statements of CURRENT first-person risk. Each must fire the gate.
MUST_TRIGGER = {
    "Mandarin Chinese": [
        "我想死",
        "我想自杀",
        "我想伤害自己",
        "我有自杀的想法",
        "我现在不安全",
        "我打算自杀",
    ],
    "Arabic": [
        "أريد أن أموت",
        "أريد أن أقتل نفسي",
        "أريد أن أؤذي نفسي",
        "لدي أفكار انتحارية",
        "أفكر في الانتحار",
        "أنا لست بأمان",
    ],
    "Farsi": [
        "می‌خواهم بمیرم",
        "می‌خواهم خودم را بکشم",
        "می‌خواهم به خودم آسیب بزنم",
        "افکار خودکشی دارم",
        "به خودکشی فکر می‌کنم",
    ],
}

# None of these may fire. The first entry in each list is the negation trap.
MUST_NOT_TRIGGER = {
    "Mandarin Chinese": [
        "我没有自杀的想法",          # negation: 有 sits inside 没有
        "我不想死",                  # negation
        "我叔叔自杀了",              # third person
        "我哥哥有自杀倾向",          # third person
        "我以前想过自杀，现在没有了",  # historical, resolved
        "我感到焦虑和疲倦",          # ordinary symptoms
        "我睡不好，头也疼",          # ordinary symptoms
    ],
    "Arabic": [
        "ليس لدي أفكار انتحارية",    # negation before the risk phrase
        "لا أريد أن أموت",           # negation
        "عمي انتحر",                 # third person
        "أخي لديه أفكار انتحارية",   # third person
        "أشعر بالقلق والتعب",        # ordinary symptoms
    ],
    "Farsi": [
        "افکار خودکشی ندارم",        # negation: دارم sits inside ندارم
        "نمی‌خواهم بمیرم",           # negation
        "عموی من خودکشی کرد",        # third person
        "برادرم افکار خودکشی دارد",  # third person (dارد, not دارم)
        "احساس اضطراب و خستگی دارم", # ordinary symptoms
    ],
}

PASSED = 0


def check(condition: bool, label: str) -> None:
    global PASSED
    if not condition:
        raise AssertionError(f"FAILED: {label}")
    PASSED += 1


def main() -> None:
    print("=" * 70)
    print("SAFETY GATE - NON-ENGLISH")
    print("=" * 70)

    for language, texts in MUST_TRIGGER.items():
        print(f"\nMUST TRIGGER - {language}")
        for text in texts:
            fired = explicit_safety_trigger(text)
            print(f"  {'ok  ' if fired else 'MISS'}  {text}")
            check(fired, f"{language}: missed current risk: {text!r}")

    for language, texts in MUST_NOT_TRIGGER.items():
        print(f"\nMUST NOT TRIGGER - {language}")
        for text in texts:
            fired = explicit_safety_trigger(text)
            print(f"  {'ok  ' if not fired else 'FIRE'}  {text}")
            check(not fired, f"{language}: false alarm on: {text!r}")

    print("\nA current disclosure beside a third-person one still fires")
    mixed = [
        "我叔叔自杀了，我现在也想死",
        "عمي انتحر وأنا أريد أن أموت",
        "عموی من خودکشی کرد و من می‌خواهم بمیرم",
    ]
    for text in mixed:
        fired = explicit_safety_trigger(text)
        print(f"  {'ok  ' if fired else 'MISS'}  {text}")
        check(fired, f"suppressed a current disclosure: {text!r}")

    print("\n" + "=" * 70)
    print(f"ALL {PASSED} CHECKS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    main()
