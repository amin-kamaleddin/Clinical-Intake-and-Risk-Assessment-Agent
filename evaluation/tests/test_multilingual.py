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


def test_patient_utterances_are_fully_localised() -> None:
    print("\n5. NO HARDCODED ENGLISH IN A NON-ENGLISH PATIENT TURN")
    # A live Mandarin intake leaked eight English patient turns, from three
    # hardcoded sources: the persona deflection lines, the "no more entries"
    # closing phrase, and the functional-difficulty option read straight out of
    # the English patient_facts. All three are now language-parameterised.
    import re
    from harness.patient_simulator import difficulty_to_response, ENGLISH_DIFFICULTY

    for name, spec in LANGUAGES.items():
        if name == "English":
            continue
        check(bool(spec.no_more_entries.strip()), f"{name}: no closing phrase")
        check(spec.no_more_entries != "No, those are all.",
              f"{name}: closing phrase is still the English one")
        check(len(spec.deflection_lines) >= 5,
              f"{name}: needs at least 5 deflection lines, has "
              f"{len(spec.deflection_lines)}")
        # A deflection carrying a number invites the interviewer to guess a score
        # ground truth cannot adjudicate. Ambiguity is the entire point.
        for line in spec.deflection_lines:
            check(not re.search(r"[0-9\u0660-\u0669\u06f0-\u06f9]", line),
                  f"{name}: deflection line contains a digit: {line!r}")
        print(f"  ok  {name:<18} closing + {len(spec.deflection_lines)} "
              f"number-free deflections")

    # difficulty maps by POSITION, so the severity the scenario specified is the
    # severity reported, and an unknown value passes through rather than being
    # guessed at.
    for index, english in enumerate(ENGLISH_DIFFICULTY):
        check(difficulty_to_response(english) == ENGLISH_DIFFICULTY[index],
              f"English difficulty {english!r} must pass through unchanged")
    check(difficulty_to_response("Mildly awkward") == "Mildly awkward",
          "an unrecognised difficulty value must pass through unchanged")
    print("  ok  difficulty maps by scale position; unknown values pass through")


def test_english_record_rule_is_enforced_not_requested() -> None:
    print("\n6. THE ENGLISH-RECORD RULE IS ENFORCED AT THE TOOL BOUNDARY")
    # The record judge compares a produced value against ENGLISH ground truth, so
    # a field left in Mandarin scores as wrong even when the intake understood it
    # perfectly. Asking the model was not enough: a live Mandarin run stored 3 of
    # 14 text fields in Chinese, including primary_problems and goals - the two
    # richest free-text fields. It is now rejected the way any invalid write is.
    import os
    os.environ.setdefault("OPENAI_API_KEY", "placeholder-no-request-is-made")
    sys.path.insert(0, str(config.CIRA_DIR))
    from graph.nodes import _reject_non_english, MAX_ENGLISH_REJECTIONS
    from core.languages import non_latin_script, PROPER_NOUN_FIELDS

    for value, script in [("易怒和烦躁", "Chinese"), ("أنثى", "Arabic or Persian"),
                          ("बिल्कुल नहीं", "Devanagari")]:
        check(non_latin_script(value) == script,
              f"{value!r} should be detected as {script}")
    # Latin stays Latin, accents included. This is the known gap: a French answer
    # left in French is NOT detectable by script and needs a reader.
    for value in ("Irritability and outbursts", "Féminin", "Sertraline 50 mg", ""):
        check(non_latin_script(value) is None, f"{value!r} must read as Latin")
    print("  ok  script detection: CJK / Arabic / Devanagari caught, Latin passes")

    # Bounded: refuse, refuse, then accept - a model that will not comply must not
    # be able to stall the intake forever, and losing the answer entirely would be
    # worse than storing it in the wrong language.
    state, results, call = {}, {}, {"id": "c1"}
    refusals = sum(
        1 for _ in range(MAX_ENGLISH_REJECTIONS + 2)
        if _reject_non_english(state, "primary_problems", "易怒和烦躁", results, call)
    )
    check(refusals == MAX_ENGLISH_REJECTIONS,
          f"expected {MAX_ENGLISH_REJECTIONS} refusals, got {refusals}")
    check("English" in results["c1"], "the refusal must say to use English")
    print(f"  ok  refuses {MAX_ENGLISH_REJECTIONS}x then accepts - cannot stall the intake")

    check(not _reject_non_english({}, "primary_problems", "Irritability", {}, call),
          "an English value must not be refused")
    for field in ("name", "address", "email"):
        check(not _reject_non_english({}, field, "张伟", {}, call),
              f"{field} is a proper noun and must be exempt")
    check(PROPER_NOUN_FIELDS, "the exempt list must not be empty")
    print(f"  ok  English passes; {len(PROPER_NOUN_FIELDS)} proper-noun fields exempt")


def test_phrases_are_distinct_across_languages() -> None:
    print("\n5. NO PHRASE IS SHARED BETWEEN TWO LANGUAGES")
    # A phrase appearing in two languages would make the score ambiguous when the
    # guard that accepts a scale answer runs without knowing the language.
    phrases = all_frequency_phrases()
    duplicates = {p for p in phrases if phrases.count(p) > 1}
    check(not duplicates, f"phrase used by more than one language: {duplicates}")
    print(f"  ok  {len(phrases)} phrases across {len(LANGUAGES)} languages, all distinct")


def test_crisis_reply_exists_and_is_detected_in_every_language() -> None:
    print("\n7. THE CRISIS RESPONSE")
    # The highest-stakes string in the system. In a live Mandarin intake the
    # crisis instruction was the ONLY English sentence in the conversation -
    # the worst possible sentence to be unreadable.
    from harness import safety_response
    sys.path.insert(0, str(config.CIRA_DIR))
    from core.languages import safety_reply_for
    from core.safety import SAFETY_REPLY

    for name, spec in LANGUAGES.items():
        reply = safety_reply_for(name, SAFETY_REPLY)
        check(bool(reply.strip()), f"{name}: no crisis reply")
        # The number does not change: these intakes are set in Toronto, so 988
        # is correct whatever the patient speaks. Translating the instruction
        # while keeping a wrong number would be worse than useless.
        check("988" in reply or "\u0669\u0668\u0668" in reply,
              f"{name}: crisis reply lost the 988 line")
        if name != "English":
            check(reply != SAFETY_REPLY, f"{name}: crisis reply is still English")
        # It must be DETECTED as a delivered response, or the safety-response
        # metric reports 0% delivery for that language - a number that looks
        # like catastrophic failure but is a detector that only reads English.
        kind = safety_response.classify_mention(reply)
        check(kind == "directive",
              f"{name}: crisis reply classified {kind!r}, not directive")
        print(f"  ok  {name:<18} translated, 988 kept, detected as {kind}")


def test_conditional_split_is_only_claimed_where_it_holds() -> None:
    print("\n8. THE DIRECTIVE / CONDITIONAL SPLIT IS NOT OVERCLAIMED")
    # The split is positional: "call 988 IF in danger" is a directive, "IF you
    # ever feel unsafe, call 988" is netting. Mandarin, Hindi and Farsi normally
    # put the conditional clause FIRST, so the rule cannot separate them and one
    # form is always misclassified. That is the rule not applying, not a missing
    # keyword, so those languages are flagged and only the combined rate is
    # reported for them.
    unreliable = {n for n, s in LANGUAGES.items()
                  if not s.conditional_distinction_reliable}
    for expected in ("Mandarin Chinese", "Hindi", "Farsi"):
        check(expected in unreliable,
              f"{expected} puts the conditional first; the split cannot hold")
    for expected in ("English", "French"):
        check(expected not in unreliable, f"{expected} should be reliable")
    print(f"  ok  split claimed only for {sorted(set(LANGUAGES) - unreliable)}")
    print(f"  ok  withheld for {sorted(unreliable)}")


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
    test_patient_utterances_are_fully_localised()
    test_english_record_rule_is_enforced_not_requested()
    test_phrases_are_distinct_across_languages()
    test_crisis_reply_exists_and_is_detected_in_every_language()
    test_conditional_split_is_only_claimed_where_it_holds()
    test_unknown_language_falls_back_to_english()
    test_case_subset_is_well_formed()
    print("\n" + "=" * 70)
    print(f"ALL {PASSED} CHECKS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    main()
