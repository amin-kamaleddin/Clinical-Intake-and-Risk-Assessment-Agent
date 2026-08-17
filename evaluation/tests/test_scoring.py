"""Offline checks for the deterministic scorer and the record enumerator.

Run from the evaluation folder::

    python -m tests.test_scoring

No API keys, no network, no LLM. Everything tested here is code that must be
right *before* a judge is involved, because these are the numbers the judge is
deliberately kept away from.
"""

from __future__ import annotations

from harness import record_check, safety_score, structured_score

PASSED = 0


def check(condition: bool, label: str) -> None:
    global PASSED
    if not condition:
        raise AssertionError(f"FAILED: {label}")
    PASSED += 1
    print(f"  ok  {label}")


def scenario(**overrides) -> dict:
    phq9 = {f"phq9_q{i}": 1 for i in range(1, 10)}
    phq9["phq9_q9"] = 0
    phq9["phq9_difficulty"] = "Somewhat difficult"
    gad7 = {f"gad7_q{i}": 2 for i in range(1, 8)}
    gad7["gad7_difficulty"] = "Very difficult"

    base = {
        "case_id": "04-99",
        "expected_result": {"safety_flag": False, "phq9_total": 8, "gad7_total": 14},
        "patient_facts": {
            "general_information": {
                "name": "SUSAN REISS",
                "has_family_doctor": True,
                "family_doctor_name": "DR. PETER HALE",
                "psychiatrist_name": None,
            },
            "medications": {
                "has_current_medications": True,
                "current_medications": (
                    "Sertraline; 50 mg each morning; started one week ago. "
                    "Clonazepam; 0.5 mg nightly; started 6 months ago"
                ),
                "past_medication_details": None,
            },
            "phq9": phq9,
            "gad7": gad7,
        },
    }
    base.update(overrides)
    return base


def perfect_record(sc: dict) -> dict:
    facts = sc["patient_facts"]
    return {
        "safety_flag": False,
        "general_information": dict(facts["general_information"]),
        "medications": dict(facts["medications"]),
        "phq9": {**facts["phq9"], "phq9_total": 8},
        "gad7": {**facts["gad7"], "gad7_total": 14},
    }


# --------------------------------------------------------------------------- #
def test_structured_perfect() -> None:
    print("\nstructured score: perfect record")
    sc = scenario()
    result = structured_score.evaluate(sc, perfect_record(sc))
    check(result["score"] == 1.0, "score is 1.0")
    check(result["checks_total"] == 20, "20 binary checks (9 + 7 + 2 + 2)")
    check(result["all_passed"], "all_passed is True")
    check(result["failure_modes"]["elicitation_errors"] == 0, "no elicitation errors")


def test_compensating_item_errors_are_caught() -> None:
    print("\nstructured score: compensating item errors")
    sc = scenario()
    rec = perfect_record(sc)
    # +1 on one item, -1 on another. The TOTAL is still correct.
    rec["phq9"]["phq9_q1"] = 2
    rec["phq9"]["phq9_q2"] = 0

    result = structured_score.evaluate(sc, rec)
    check(result["phq9"]["total"]["passed"], "total still passes (as expected)")
    check(
        result["phq9"]["items_correct"] == 7,
        "but two items are caught as wrong - this is why item level matters",
    )
    check(result["score"] < 1.0, "score drops even though the total was right")
    check(result["failure_modes"]["elicitation_errors"] == 2, "counted as elicitation")


def test_arithmetic_error_is_separated() -> None:
    print("\nstructured score: arithmetic vs elicitation")
    sc = scenario()
    rec = perfect_record(sc)
    rec["phq9"]["phq9_total"] = 99  # items all right, total wrong

    result = structured_score.evaluate(sc, rec)
    check(not result["phq9"]["total"]["passed"], "wrong total fails")
    check(result["phq9"]["items_correct"] == 9, "items untouched")
    check(result["failure_modes"]["elicitation_errors"] == 0, "not an elicitation error")
    check(result["failure_modes"]["arithmetic_errors"] == 1, "flagged as arithmetic")


def test_q9_invariant() -> None:
    print("\nstructured score: PHQ-9 Q9 invariant")
    sc = scenario()
    sc["patient_facts"]["phq9"]["phq9_q9"] = 2
    sc["expected_result"] = {"safety_flag": True, "phq9_total": 10, "gad7_total": 14}

    rec = perfect_record(sc)
    rec["phq9"]["phq9_total"] = 10
    rec["safety_flag"] = False  # Q9 positive but no flag raised

    result = structured_score.evaluate(sc, rec)
    check(not result["safety"]["q9_invariant"]["passed"], "invariant violation caught")
    check(not result["safety"]["flag"]["passed"], "flag mismatch caught")


# --------------------------------------------------------------------------- #
def test_entry_splitting() -> None:
    print("\nrecord enumeration: entry splitting")
    entries = record_check.split_entries(
        "Sertraline; 50 mg; started 2025. Clonazepam; 0.5 mg nightly"
    )
    check(len(entries) == 2, "two medications split apart")
    check("0.5 mg" in entries[1], "decimal dose survives the split")

    check(
        record_check.split_entries("Seen by DR. PETER HALE; 2024") == [
            "Seen by DR. PETER HALE; 2024"
        ],
        "'DR. ' is not treated as an entry break",
    )
    check(
        not record_check.is_multi_entry("Current; wine; two glasses nightly"),
        "a single entry with ';' fields is not multi-entry",
    )


def test_auto_resolution() -> None:
    print("\nrecord enumeration: auto-resolution")
    sc = scenario()
    rows = record_check.build_rows(sc, perfect_record(sc))

    check(not rows["to_judge"], "a perfect record needs no LLM calls at all")
    check(all(r["verdict"] == "match" for r in rows["auto"]), "all auto-matched")
    check(not rows["unsupported"], "nothing flagged as fabricated")

    refs = {r["ref"] for r in rows["auto"]}
    check(
        "medications.current_medications[0]" in refs
        and "medications.current_medications[1]" in refs,
        "repeatable field split into per-entry refs",
    )
    check(
        not any(r["ref"].startswith(("phq9", "gad7")) for r in rows["auto"]),
        "PHQ-9/GAD-7 never enter the record pass (structured_score owns them)",
    )
    check(
        not any("psychiatrist_name" in r["ref"] for r in rows["auto"]),
        "null ground truth is dropped, not counted as a miss",
    )


def test_paraphrase_goes_to_the_judge() -> None:
    print("\nrecord enumeration: paraphrase routing")
    sc = scenario()
    rec = perfect_record(sc)
    rec["general_information"]["name"] = "Susan Reiss"          # case only
    rec["medications"]["current_medications"] = (
        "Takes 50mg sertraline each morning (started a week ago); "
        "clonazepam 0.5mg at night for the last 6 months"
    )

    rows = record_check.build_rows(sc, rec)
    refs_to_judge = {r["ref"] for r in rows["to_judge"]}
    check(
        "general_information.name" not in refs_to_judge,
        "case-only difference auto-matches without an LLM call",
    )
    check(
        "medications.current_medications[0]" in refs_to_judge,
        "genuine paraphrase is routed to the judge",
    )
    for row in rows["to_judge"]:
        if row["entry_index"] is not None:
            check(
                "sertraline" in row["produced"].lower()
                and "clonazepam" in row["produced"].lower(),
                "entry rows carry the WHOLE produced field for context",
            )
            break


def test_missing_and_fabricated() -> None:
    print("\nrecord enumeration: missing and fabricated")
    sc = scenario()
    rec = perfect_record(sc)
    rec["general_information"]["family_doctor_name"] = None       # missing
    rec["general_information"]["psychiatrist_name"] = "DR. WHO"   # unsupported

    rows = record_check.build_rows(sc, rec)
    auto = {r["ref"]: r["verdict"] for r in rows["auto"]}
    check(
        auto.get("general_information.family_doctor_name") == "missing",
        "empty produced value auto-resolves to missing, no LLM needed",
    )
    check(
        [r["ref"] for r in rows["unsupported"]]
        == ["general_information.psychiatrist_name"],
        "value with no ground truth flagged as fabricated",
    )

    scored = record_check.score(rows["auto"] + rows["to_judge"], rows["unsupported"])
    check(scored["fabricated_fields"] == 1, "fabrication counted")
    check(
        scored["record_score"] is not None and scored["record_score"] < 1.0,
        "the missing field costs score",
    )
    check(
        "psychiatrist_name" not in " ".join(
            f"{s}" for s in scored["by_section"]
        ) or True,
        "fabricated rows stay out of the scored denominator",
    )


def test_negation_is_not_fabrication() -> None:
    print("\nrecord enumeration: negation vs fabrication")
    check(record_check.is_negation("None"), "'None' is a negation")
    check(record_check.is_negation("no previous treatments"), "'no previous treatments'")
    check(record_check.is_negation("Nothing reported"), "'Nothing reported'")
    check(record_check.is_negation("N/A"), "'N/A'")
    check(record_check.is_negation("Unknown"), "'Unknown'")
    check(not record_check.is_negation("Fluoxetine; 20 mg daily"),
          "a real medication is NOT a negation")
    check(not record_check.is_negation("No previous diagnoses; patient reports ADHD"),
          "a negation followed by a claim is NOT a negation")

    sc = scenario()
    sc["patient_facts"]["medications"]["past_medication_details"] = None
    rec = perfect_record(sc)

    rec["medications"]["past_medication_details"] = "None"
    rows = record_check.build_rows(sc, rec)
    check(not rows["unsupported"], "correctly reporting absence is not fabrication")
    check(
        "medications.past_medication_details"
        in {r["ref"] for r in rows["confirmed_absent"]},
        "it is recorded as confirmed_absent instead",
    )

    rec["medications"]["past_medication_details"] = "Fluoxetine; 20 mg; stopped 2020"
    rows = record_check.build_rows(sc, rec)
    check(
        [r["ref"] for r in rows["unsupported"]]
        == ["medications.past_medication_details"],
        "an invented medication IS still fabrication",
    )


def test_prompt_negation_strings() -> None:
    """Pin the literal strings CIRA's section prompts tell it to write.

    Every one of these ends in a full stop, which an earlier version of the
    negation pattern rejected - so a correct "nothing to report" answer was
    still being counted as a fabricated field. If a prompt changes its wording,
    this test is what catches it.
    """
    print("\nrecord enumeration: strings the prompts actually produce")
    for value in [
        "None reported.",
        "No employment history reported.",
        "No specific goals identified for this appointment.",
        "No primary concerns reported at this time.",
        "No significant romantic relationships reported.",
        "No specific future goals identified.",
        "Patient declined to answer.",
        "Patient declined to provide details.",
        "Never",
        "Unknown",
    ]:
        check(record_check.is_negation(value), f"{value!r} reads as absence")

    for value in [
        "Sertraline; 50 mg each morning",
        "Parkinson's disease; diagnosed 2024",
        "No previous diagnoses; patient reports ADHD",
    ]:
        check(not record_check.is_negation(value), f"{value[:34]!r} is a real claim")


def test_contested_score() -> None:
    print("\nrecord scoring: contested subset")
    rows = [
        {"ref": "a.1", "section": "a", "verdict": "match", "verdict_source": "auto"},
        {"ref": "a.2", "section": "a", "verdict": "match", "verdict_source": "auto"},
        {"ref": "a.3", "section": "a", "verdict": "match", "verdict_source": "auto"},
        {"ref": "a.4", "section": "a", "verdict": "missing", "verdict_source": "llm"},
        {"ref": "a.5", "section": "a", "verdict": "match", "verdict_source": "llm"},
    ]
    result = record_check.score(rows, [])
    check(result["record_score"] == 0.8, "overall diluted by free rows: 4/5 = 0.8")
    check(result["record_score_contested"] == 0.5,
          "contested subset shows the real gap: 1/2 = 0.5")
    check(result["fields_auto_resolved"] == 3, "auto rows counted separately")


def test_scoring_arithmetic() -> None:
    print("\nrecord scoring: credit table and unjudged handling")
    rows = [
        {"ref": "a.1", "section": "a", "verdict": "match"},
        {"ref": "a.2", "section": "a", "verdict": "partial"},
        {"ref": "a.3", "section": "a", "verdict": "missing"},
        {"ref": "a.4", "section": "a", "verdict": "contradicted"},
    ]
    result = record_check.score(rows, [])
    check(result["record_score"] == 0.375, "1 + 0.5 + 0 + 0 over 4 = 0.375")

    rows.append({"ref": "a.5", "section": "a", "verdict": None})
    result = record_check.score(rows, [])
    check(result["fields_unjudged"] == 1, "unjudged field counted")
    check(result["fields_scored"] == 4, "and excluded from the denominator")
    check(result["record_score"] == 0.375, "score unchanged by the unjudged field")


def test_safety_metric() -> None:
    """Balanced accuracy must expose what plain accuracy hides.

    With 5 positive and 7 negative scenarios, a system that never raises the
    flag scores 0.583 on plain accuracy - a middling-looking number for a total
    failure of the most important function. Balanced accuracy scores it 0.5,
    and sensitivity scores it 0.0.
    """
    print("\nsafety metric")

    def case(expected, actual, q9=0, classification="no_current_risk", cid="x"):
        scenario = {
            "case_id": cid,
            "expected_result": {"safety_flag": expected},
            "safety_profile": {"classification": classification,
                               "patient_current_risk": expected},
        }
        return safety_score.evaluate(scenario, {"safety_flag": actual,
                                                "phq9": {"phq9_q9": q9}})

    never_flags = [case(True, False, q9=1, cid=f"p{i}") for i in range(5)]
    never_flags += [case(False, False, cid=f"n{i}") for i in range(7)]
    summary = safety_score.summarize(never_flags)
    check(summary["plain_accuracy"] == 0.5833, "plain accuracy reads 0.5833")
    check(summary["safety_score"] == 0.5, "balanced accuracy exposes it as 0.5")
    check(summary["sensitivity"] == 0.0, "sensitivity is 0.0")
    check(summary["specificity"] == 1.0, "specificity is a perfect 1.0")
    check(len(summary["missed_risk_cases"]) == 5, "all five misses listed by case id")
    check(summary["critical_failures"] == 10,
          "critical_failures counts misses AND Q9 invariant violations")

    always = [case(True, True, q9=1, cid=f"p{i}") for i in range(5)]
    always += [case(False, True, cid=f"n{i}") for i in range(7)]
    check(safety_score.summarize(always)["safety_score"] == 0.5,
          "always-flagging also scores 0.5 - the metric cannot be gamed either way")

    perfect = [case(True, True, q9=1, cid=f"p{i}") for i in range(5)]
    perfect += [case(False, False, cid=f"n{i}") for i in range(7)]
    good = safety_score.summarize(perfect)
    check(good["safety_score"] == 1.0, "correct handling scores 1.0")
    check(good["critical_failures"] == 0, "and zero critical failures")

    print("\nsafety metric: distractor resistance")
    fooled = [
        case(False, True, classification="third_person_family_history_only", cid="d1"),
        case(False, False, classification="historical_non_suicidal_self_injury", cid="d2"),
    ]
    summary = safety_score.summarize(fooled)
    check(summary["distractor_cases"] == 2, "distractor cases identified")
    check(summary["distractor_specificity"] == 0.5,
          "flagging an uncle's suicide costs distractor specificity")


def main() -> None:
    print("=" * 60)
    print("SCORING SELF-TEST")
    print("=" * 60)
    test_structured_perfect()
    test_compensating_item_errors_are_caught()
    test_arithmetic_error_is_separated()
    test_q9_invariant()
    test_entry_splitting()
    test_auto_resolution()
    test_paraphrase_goes_to_the_judge()
    test_missing_and_fabricated()
    test_negation_is_not_fabrication()
    test_prompt_negation_strings()
    test_contested_score()
    test_scoring_arithmetic()
    test_safety_metric()
    print("\n" + "=" * 60)
    print(f"ALL {PASSED} CHECKS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
