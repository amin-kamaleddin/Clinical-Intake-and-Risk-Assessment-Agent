"""Multilingual evaluation: the pieces that must work outside English.

A non-English intake works only because three things stay language-independent -
the item LABEL, the response DIGITS, and the English RECORD. This file pins all
three, plus the pieces that had to be translated.

Every case here comes from a real failure or a real transcript, not from
imagination:

  * "GAD-7 问题 1：" is what CIRA actually wrote in a live Mandarin intake, in the
    same conversation where it wrote "**PHQ-9 Question 1:**". All seven GAD-7
    items fell through to the LLM and lost their ground-truth answers; all nine
    PHQ-9 items resolved. One matcher has to handle both.
  * Arabic and Farsi number items in their own numerals, so "السؤال ٣" carries no
    ASCII digit at all.

Offline. No API keys, no network.
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from harness import config  # noqa: E402
from harness.multilingual_cases import MULTILINGUAL_CASE_IDS  # noqa: E402
from harness.patient_simulator import (  # noqa: E402
    PatientSimulator,
    _normalize_digits,
)

sys.path.insert(0, str(config.CIRA_DIR))
from core.languages import LANGUAGES, all_frequency_phrases, get  # noqa: E402

PASSED = 0


def check(condition: bool, label: str) -> None:
    global PASSED
    if not condition:
        raise AssertionError(f"FAILED: {label}")
    PASSED += 1


# (text, instrument, max_item, expected_item)
LABEL_FORMATS = [
    ("**PHQ-9 Question 1:** 做事时缺乏兴趣或乐趣", "phq9", 9, 1),
    ("GAD-7 问题 1：在过去两周里，您有多经常感到紧张？", "gad7", 7, 1),
    ("GAD-7 问题 7：您有多经常感到害怕？", "gad7", 7, 7),
    ("PHQ-9 السؤال ٣: خلال الأسبوعين الماضيين", "phq9", 9, 3),
    ("GAD-7 السؤال ٧: هل شعرت بالخوف؟", "gad7", 7, 7),
    ("GAD-7 سوال ۵: چقدر بی‌قرار بودید؟", "gad7", 7, 5),
    ("PHQ-9 سوال ۹: افکار آسیب به خود؟", "phq9", 9, 9),
    ("PHQ-9 प्रश्न 8: क्या आप धीमे हो गए?", "phq9", 9, 8),
    ("PHQ-9 Question 4 : fatigue ou manque d'énergie", "phq9", 9, 4),
    ("GAD-7 question 4: trouble relaxing?", "gad7", 7, 4),
]


def test_item_labels_resolve_in_every_script() -> None:
    print("\n1. ITEM LABELS RESOLVE WHATEVER THE LANGUAGE")
    for text, instrument, maximum, expected in LABEL_FORMATS:
        got = PatientSimulator._question_number(text, instrument, maximum)
        check(got == expected,
              f"{instrument} label {text[:40]!r}: got {got}, want {expected}")
        print(f"  ok  {instrument} item {got}  {text[:46]}")


def test_non_ascii_digits_normalise() -> None:
    print("\n2. NON-ASCII NUMERALS")
    for raw, want in [("٣", "3"), ("۵", "5"), ("٠٩", "09"), ("7", "7")]:
        got = _normalize_digits(raw)
        check(got == want, f"{raw!r} -> {got!r}, want {want!r}")
        print(f"  ok  {raw!r} -> {got!r}")


def test_wrong_instrument_is_not_matched() -> None:
    print("\n3. THE PERMISSIVE MATCHER DOES NOT CROSS INSTRUMENTS")
    # The fallback allows any non-digit filler, so it must still refuse a label
    # that names the OTHER instrument - resolving a GAD-7 item to a PHQ-9 key is
    # how an entire GAD-7 record once came back as a copy of the PHQ-9 record.
    check(PatientSimulator._question_number("GAD-7 问题 3：", "phq9", 9) is None,
          "a GAD-7 label resolved as a PHQ-9 item")
    print("  ok  GAD-7 label does not resolve as phq9")
    check(PatientSimulator._question_number("PHQ-9 问题 3：", "gad7", 7) is None,
          "a PHQ-9 label resolved as a GAD-7 item")
    print("  ok  PHQ-9 label does not resolve as gad7")


def test_every_language_has_complete_instrument_wording() -> None:
    print("\n4. EVERY LANGUAGE CAN ADMINISTER BOTH INSTRUMENTS")
    for name, spec in LANGUAGES.items():
        check(len(spec.frequency_phrases) == 4, f"{name}: needs 4 frequency phrases")
        check(len(spec.difficulty_phrases) == 4, f"{name}: needs 4 difficulty phrases")
        check(all(p.strip() for p in spec.frequency_phrases), f"{name}: empty phrase")
        check(len(set(spec.frequency_phrases)) == 4, f"{name}: duplicate phrases")
        check("?" in spec.question_marks, f"{name}: must accept the Latin '?'")
        print(f"  ok  {name:<18} {spec.frequency_phrases[0]} ... {spec.frequency_phrases[3]}")


def test_phrases_are_distinct_across_languages() -> None:
    print("\n5. NO PHRASE IS SHARED BETWEEN TWO LANGUAGES")
    # A phrase appearing in two languages would make the score ambiguous when the
    # guard that accepts a scale answer runs without knowing the language.
    phrases = all_frequency_phrases()
    duplicates = {p for p in phrases if phrases.count(p) > 1}
    check(not duplicates, f"phrase used by more than one language: {duplicates}")
    print(f"  ok  {len(phrases)} phrases across {len(LANGUAGES)} languages, all distinct")


def test_unknown_language_falls_back_to_english() -> None:
    print("\n6. AN UNKNOWN LANGUAGE FALLS BACK TO ENGLISH")
    # Matches the prompt's own rule, so the agent and the harness cannot
    # disagree about what an unrecognised name means. The experiment RUNNER
    # refuses instead of falling back - see tools/run_multilingual.py - because
    # there a silent fallback would mislabel a whole output tree.
    check(get("Klingon").name == "English", "unknown language did not fall back")
    check(get("Farsi").name == "Farsi", "a known language was not returned")
    print("  ok  unknown -> English, known -> itself")


def test_case_subset_is_well_formed() -> None:
    print("\n7. THE 10-CASE SUBSET")
    import json
    scenarios = json.loads(config.SCENARIO_FILE.read_text(encoding="utf-8"))
    by_id = {s["case_id"]: s for s in scenarios}
    check(len(MULTILINGUAL_CASE_IDS) == 10, "must be exactly 10 cases")
    check(len(set(MULTILINGUAL_CASE_IDS)) == 10, "case ids must be distinct")
    for case_id in MULTILINGUAL_CASE_IDS:
        check(case_id in by_id, f"{case_id} is not in the scenario file")
    risk = [c for c in MULTILINGUAL_CASE_IDS
            if by_id[c]["expected_result"]["safety_flag"]]
    check(len(risk) >= 3, f"needs at least 3 risk cases, has {len(risk)}")
    classes = {by_id[c]["safety_profile"]["classification"]
               for c in MULTILINGUAL_CASE_IDS}
    check(len(classes) >= 8, f"needs at least 8 safety classes, has {len(classes)}")
    print(f"  ok  10 cases, {len(risk)} at risk, {len(classes)} safety classes")


def main() -> None:
    print("=" * 70)
    print("MULTILINGUAL EVALUATION")
    print("=" * 70)
    test_item_labels_resolve_in_every_script()
    test_non_ascii_digits_normalise()
    test_wrong_instrument_is_not_matched()
    test_every_language_has_complete_instrument_wording()
    test_phrases_are_distinct_across_languages()
    test_unknown_language_falls_back_to_english()
    test_case_subset_is_well_formed()
    print("\n" + "=" * 70)
    print(f"ALL {PASSED} CHECKS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    main()
