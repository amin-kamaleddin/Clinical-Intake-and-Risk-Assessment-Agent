"""Regression tests for the deterministic safety gate.

Run from the cira folder::

    python -m tests.test_safety_gate

No API keys, no network, no model. ``explicit_safety_trigger`` is pure regex.

Both directions are pinned, because they fail differently:

* A **false negative** - a real current disclosure the gate misses - is the
  worst outcome this system can produce. Those cases are listed in
  ``MUST_TRIGGER`` and are the reason for the widened patterns and the
  clause-level exclusion logic.
* A **false positive** - flagging a historical, third-person, negated or
  hypothetical statement - costs clinician time and, at volume, causes alarm
  fatigue. Those cases are in ``MUST_NOT_TRIGGER``.

The gate is only one of three paths to the flag (the others are PHQ-9 item 9
and the model's raise_safety_flag tool), so a miss here is not necessarily a
miss overall. It is still the only path that cannot be talked out of firing,
which is why it is tested exhaustively.
"""

from __future__ import annotations

import sys
import types

# core.config imports dotenv; stub it so this runs with no dependencies.
if "dotenv" not in sys.modules:
    _dotenv = types.ModuleType("dotenv")
    _dotenv.load_dotenv = lambda **kwargs: None
    sys.modules["dotenv"] = _dotenv

from core.safety import explicit_safety_trigger  # noqa: E402


# Every one of these MUST fire. Several were silent before the gate was widened.
MUST_TRIGGER = [
    # Previously missed entirely - no pattern covered them.
    "I am not safe right now.",
    "I'm not safe.",
    "I am suicidal.",
    "I'm currently suicidal.",
    "I feel suicidal.",
    "I can't keep myself safe.",
    "I cannot stay safe.",
    "I have suicidal thoughts.",
    "I'm having thoughts of killing myself.",
    "I have a plan to kill myself.",
    "I have a plan and intent to end my life.",
    "I am going to kill myself.",
    "I mean to do it.",
    "I want to end it all.",

    # Previously missed because an exclusion elsewhere in the message
    # suppressed the whole thing.
    "My brother died by suicide and I currently want to die.",
    "My mother was suicidal years ago, but I want to kill myself now.",
    "I used to self-harm as a teenager. I am not safe right now.",
    "He has been suicidal before; I am suicidal too.",

    # Already covered - must keep working.
    "I want to die.",
    "I want to kill myself.",
    "Sometimes I feel I would be better off dead.",
    "I plan to hurt myself.",
    "I don't want to be alive.",
]


# None of these may fire. Flagging them is the characteristic failure of a
# keyword matcher and the thing the scenario distractors exist to catch.
MUST_NOT_TRIGGER = [
    # Third person / family history
    "My maternal uncle died by suicide in 2008.",
    "My brother died by suicide.",
    "My friend is suicidal.",
    "My mother has been suicidal before.",

    # Clear denial
    "I am not suicidal.",
    "I'm not thinking about suicide.",
    "I have never wanted to hurt myself.",
    "I do not have any current suicidal thoughts or immediate safety concern.",

    # Historical, resolved
    "I harmed myself several years ago, but I do not feel that way now.",
    "I used to want to die when I was younger.",
    "I self-harmed in the past.",

    # Ordinary clinical content
    "I have anxiety, poor sleep, and trouble concentrating.",
    "I feel down and tired most days.",
    "I take sertraline 50 mg each morning.",
    "My appetite is lower at lunch.",
    "School has been difficult and I get angry.",

    # Hypothetical
    "Hypothetically, what if someone felt that way?",
    "",
    "   ",
]


PASSED = 0


def check(condition: bool, label: str) -> None:
    global PASSED
    if not condition:
        raise AssertionError(f"FAILED: {label}")
    PASSED += 1


def main() -> None:
    print("=" * 66)
    print("SAFETY GATE REGRESSION TEST")
    print("=" * 66)

    print("\nMUST TRIGGER (a miss here is the worst failure mode)")
    for text in MUST_TRIGGER:
        fired = explicit_safety_trigger(text)
        print(f"  {'ok ' if fired else 'MISS'}  {text[:62]!r}")
        check(fired, f"missed current risk: {text!r}")

    print("\nMUST NOT TRIGGER (false alarms cost trust)")
    for text in MUST_NOT_TRIGGER:
        fired = explicit_safety_trigger(text)
        print(f"  {'ok ' if not fired else 'FIRE'}  {text[:62]!r}")
        check(not fired, f"false alarm on: {text!r}")

    print("\nnon-string input is handled")
    for value in (None, 123, [], {}):
        check(explicit_safety_trigger(value) is False, f"non-string {value!r}")

    print("\n" + "=" * 66)
    print(f"ALL {PASSED} CHECKS PASSED")
    print("=" * 66)


if __name__ == "__main__":
    main()
