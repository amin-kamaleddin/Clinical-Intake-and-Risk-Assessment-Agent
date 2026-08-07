"""Stage 3 - deterministic scoring.

Runs the *same* deterministic checks over any system's saved records and
transcripts. This replaces the three copies of scoring logic that used to live
inline in the CIRA driver, the rule-based driver, and the old
``evaluate_records.py``.

Reads:   outputs/<system>/records/case_XX.json
         outputs/<system>/transcripts/case_XX.json
Writes:  outputs/reports/<system>_deterministic.json

Run directly for one system::

    python -m harness.stages.score_records --system cira
    python -m harness.stages.score_records --system rule_based
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from harness import config
from harness import personas
from harness import structured_score
from harness.common import (
    asked_for_additional_medications,
    consecutive_duplicate_questions,
    expected_medication_entry_count,
    medication_capture_check,
    normalize_text,
    safety_response_count,
)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_scenarios(case_filter: str | None = None) -> list[dict]:
    scenarios = load_json(config.SCENARIO_FILE)
    if not isinstance(scenarios, list):
        raise ValueError("cira_scenarios.json must contain a JSON list.")
    if case_filter:
        scenarios = [s for s in scenarios if s.get("case_id") == case_filter]
        if not scenarios:
            raise ValueError(f"Scenario not found: {case_filter}")
    return scenarios


# --------------------------------------------------------------------------- #
# Record shape helpers (support both top-level and wrapped records)
# --------------------------------------------------------------------------- #
def resolve_case_persona(system: str, scenario: dict, record: dict | None) -> str:
    """Which persona this case actually ran against.

    Prefer what the artifacts recorded (that is what really happened) and fall
    back to re-deriving the assignment, so records written before personas
    existed still get labelled instead of dropping out of the breakdown.
    """
    if isinstance(record, dict) and record.get("persona_id"):
        return str(record["persona_id"])

    transcript_file = config.transcript_path(system, scenario["case_id"])
    if transcript_file.exists():
        transcript = load_json(transcript_file)
        if transcript.get("persona_id"):
            return str(transcript["persona_id"])

    return personas.resolve_assignment().get(
        scenario["case_id"], personas.DEFAULT_PERSONA_ID
    )


def unwrap_record(record: dict) -> dict:
    for key in ("state", "final_state", "record", "data"):
        nested = record.get(key)
        if isinstance(nested, dict):
            return nested
    return record


def extract_actual_result(record: dict) -> dict:
    state = unwrap_record(record)
    phq9 = state.get("phq9", {})
    gad7 = state.get("gad7", {})

    phq9_total = phq9.get("phq9_total") if isinstance(phq9, dict) else None
    gad7_total = gad7.get("gad7_total") if isinstance(gad7, dict) else None
    if phq9_total is None:
        phq9_total = state.get("phq9_total")
    if gad7_total is None:
        gad7_total = state.get("gad7_total")

    return {
        "state": state,
        "safety_flag": state.get("safety_flag"),
        "phq9_total": phq9_total,
        "gad7_total": gad7_total,
        "completed_sections": state.get("sections_completed", []),
    }


def transcript_checks(transcript_file: Path | None, scenario: dict) -> dict:
    if transcript_file is None or not transcript_file.exists():
        return {
            "available": False,
            "asked_for_additional_medications": None,
            "no_consecutive_duplicate_cira_question": None,
            "safety_response_not_repeated": None,
        }

    transcript_data = load_json(transcript_file)
    conversation = transcript_data.get("conversation", [])
    cira_messages = [
        normalize_text(turn.get("message"))
        for turn in conversation
        if turn.get("speaker") == "CIRA"
    ]

    duplicates = consecutive_duplicate_questions(cira_messages)
    safety_count = safety_response_count(cira_messages)
    asks_for_more = asked_for_additional_medications(cira_messages)
    expected_count = expected_medication_entry_count(scenario)

    return {
        "available": True,
        "asked_for_additional_medications": (expected_count <= 1) or asks_for_more,
        "no_consecutive_duplicate_cira_question": not duplicates,
        "safety_response_not_repeated": safety_count <= 1,
        "details": {
            "expected_medication_entry_count": expected_count,
            "asked_for_more": asks_for_more,
            "duplicate_questions": duplicates,
            "safety_response_count": safety_count,
        },
    }


# --------------------------------------------------------------------------- #
# Per-case evaluation
# --------------------------------------------------------------------------- #
def evaluate_case(system: str, scenario: dict, record_file: Path) -> dict:
    expected = scenario["expected_result"]
    record = load_json(record_file)
    actual = extract_actual_result(record)

    medication_check = medication_capture_check(scenario, actual["state"].get("medications"))
    all_sections_done = set(config.CANONICAL_SECTIONS) <= set(actual["completed_sections"])

    transcript_file = config.transcript_path(system, scenario["case_id"])
    conversation = transcript_checks(transcript_file, scenario)

    # Questionnaires and the safety flag are scored by harness.structured_score
    # and deliberately do NOT appear below. Scoring them twice, by two different
    # methods, was the duplication this refactor removes.
    structured = structured_score.evaluate(scenario, actual["state"])

    checks = {
        "all_sections_completed": {
            "expected": config.CANONICAL_SECTIONS,
            "actual": actual["completed_sections"],
            "passed": all_sections_done,
        },
        # Drug-NAME coverage only. Whether the dose/date/side-effect detail was
        # captured is the record judge's job, since that needs paraphrase
        # tolerance a substring check cannot provide.
        "medication_coverage": {
            "expected": "all identifiable medication entries captured",
            "actual": medication_check,
            "passed": medication_check["passed"],
        },
    }

    if conversation["available"]:
        for name in (
            "asked_for_additional_medications",
            "no_consecutive_duplicate_cira_question",
            "safety_response_not_repeated",
        ):
            checks[name] = {
                "expected": True,
                "actual": conversation[name],
                "passed": conversation[name] is True,
            }

    passed_checks = sum(check["passed"] for check in checks.values())
    total_checks = len(checks)

    return {
        "case_id": config.short_case_id(scenario["case_id"]),
        "scenario_case_id": scenario["case_id"],
        "title": scenario["title"],
        "system": system,
        "persona_id": resolve_case_persona(system, scenario, record),
        "record_file": str(record_file),
        "transcript_file": str(transcript_file) if transcript_file.exists() else None,
        "status": (
            "PASS"
            if passed_checks == total_checks and structured["all_passed"]
            else "FAIL"
        ),
        # The headline deterministic number: PHQ-9/GAD-7 items and totals plus
        # the safety flag, 20 binary checks, unweighted.
        "structured_score": structured["score"],
        "structured": structured,
        # Process checks are reported alongside, not folded in - they measure
        # intake conduct, not clinical values.
        "process_score": round(passed_checks / total_checks, 4),
        "score": structured["score"],
        "passed_checks": passed_checks,
        "total_checks": total_checks,
        "checks": checks,
        "completed_sections": actual["completed_sections"],
        "conversation_details": conversation.get("details"),
    }


# --------------------------------------------------------------------------- #
# Summary
# --------------------------------------------------------------------------- #
METRIC_NAMES = [
    "all_sections_completed",
    "medication_coverage",
    "asked_for_additional_medications",
    "no_consecutive_duplicate_cira_question",
    "safety_response_not_repeated",
]


def _metric_accuracy(results: list[dict]) -> dict:
    accuracy = {}
    for name in METRIC_NAMES:
        available = [r["checks"][name]["passed"] for r in results if name in r["checks"]]
        accuracy[name] = round(sum(available) / len(available), 4) if available else None
    return accuracy


def build_persona_breakdown(results: list[dict]) -> dict:
    """Pass rate and per-metric accuracy split by patient persona.

    This is the point of the personas: an aggregate number hides whether a
    system is competent overall or merely competent with easy patients. Ordered
    easiest -> hardest so the degradation curve reads left to right.
    """
    valid = [r for r in results if r["status"] in {"PASS", "FAIL"}]
    breakdown = {}

    for persona_id in personas.PERSONA_IDS:
        subset = [r for r in valid if r.get("persona_id") == persona_id]
        if not subset:
            continue
        passed = sum(r["status"] == "PASS" for r in subset)
        breakdown[persona_id] = {
            "label": personas.PERSONAS[persona_id].label,
            "difficulty_rank": personas.PERSONAS[persona_id].difficulty_rank,
            "cases": len(subset),
            "case_ids": sorted(r["scenario_case_id"] for r in subset),
            "passed": passed,
            "pass_rate": round(passed / len(subset), 4),
            "mean_structured_score": round(
                sum(r["structured_score"] for r in subset) / len(subset), 4
            ),
            "mean_process_score": round(
                sum(r["process_score"] for r in subset) / len(subset), 4
            ),
            "structured": structured_score.summarize(
                [r["structured"] for r in subset]
            ),
            "metric_accuracy": _metric_accuracy(subset),
        }

    return breakdown


def build_summary(system: str, scenarios: list[dict], results: list[dict]) -> dict:
    valid = [r for r in results if r["status"] in {"PASS", "FAIL"}]

    # Normalize BOTH sides to the short case id so the sets are directly
    # comparable regardless of which id format a scenario or result carries.
    # (An earlier version compared full ids like "04-03" against short "03",
    # which made every safety case look both missed and unexpected.)
    expected_safety = {
        config.short_case_id(s["case_id"])
        for s in scenarios
        if s["expected_result"]["safety_flag"]
    }
    # Read the flag from the structured result, which now owns safety scoring.
    actual_safety = {
        config.short_case_id(r["scenario_case_id"])
        for r in valid
        if r.get("structured", {}).get("safety", {}).get("flag", {}).get("actual")
    }

    metric_accuracy = _metric_accuracy(valid)

    return {
        "system": system,
        "total_cases": len(scenarios),
        "evaluated_cases": len(valid),
        "passed": sum(r["status"] == "PASS" for r in valid),
        "failed": sum(r["status"] == "FAIL" for r in valid),
        "errors": sum(r["status"] == "ERROR" for r in results),
        "expected_safety_flags": len(expected_safety),
        "actual_safety_flags": len(actual_safety),
        "missed_safety_cases": sorted(expected_safety - actual_safety),
        "unexpected_safety_cases": sorted(actual_safety - expected_safety),
        "metric_accuracy": metric_accuracy,
        "structured": structured_score.summarize(
            [r["structured"] for r in valid if "structured" in r]
        ),
        "by_persona": build_persona_breakdown(results),
    }


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def run(system: str, case_filter: str | None = None, verbose: bool = True) -> dict:
    scenarios = load_scenarios(case_filter)
    results = []

    if verbose:
        print("=" * 72)
        print(f"DETERMINISTIC SCORING - {system}")
        print("Scenarios:", len(scenarios))
        print("=" * 72)

    for scenario in scenarios:
        record_file = config.record_path(system, scenario["case_id"])
        if not record_file.exists():
            results.append({
                "case_id": config.short_case_id(scenario["case_id"]),
                "scenario_case_id": scenario["case_id"],
                "title": scenario["title"],
                "system": system,
                "status": "ERROR",
                "error": f"No record at {record_file}",
            })
            if verbose:
                print(f"Case {scenario['case_id']}: ERROR - no record")
            continue
        try:
            result = evaluate_case(system, scenario, record_file)
            results.append(result)
            if verbose:
                print(f"Case {scenario['case_id']} [{result['persona_id']:>8}]: "
                      f"{result['status']} | structured="
                      f"{result['structured_score']:.3f} "
                      f"({result['structured']['checks_passed']}"
                      f"/{result['structured']['checks_total']}) | process="
                      f"{result['passed_checks']}/{result['total_checks']}")
        except Exception as error:  # noqa: BLE001 - report and continue
            results.append({
                "case_id": config.short_case_id(scenario["case_id"]),
                "scenario_case_id": scenario["case_id"],
                "title": scenario["title"],
                "system": system,
                "record_file": str(record_file),
                "status": "ERROR",
                "error": str(error),
            })
            if verbose:
                print(f"Case {scenario['case_id']}: ERROR - {error}")

    summary = build_summary(system, scenarios, results)
    report = {"summary": summary, "cases": results}

    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = config.deterministic_report_path(system)
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if verbose:
        struct = summary["structured"]
        print(f"\n{system}: {summary['passed']}/{summary['evaluated_cases']} passed")
        print(f"  structured score: {struct['mean_score']} "
              f"(PHQ-9 items {struct['phq9_item_accuracy']}, "
              f"GAD-7 items {struct['gad7_item_accuracy']}, "
              f"safety flag {struct['safety_flag_accuracy']})")
        print(f"  failure modes: {struct['total_elicitation_errors']} elicitation, "
              f"{struct['total_arithmetic_errors']} arithmetic")
        if summary["by_persona"]:
            print("By persona (easiest -> hardest):")
            for persona_id, stats in summary["by_persona"].items():
                print(f"  {persona_id:>8}: {stats['passed']}/{stats['cases']} passed "
                      f"| structured {stats['mean_structured_score']}")
        print("Report saved to:", report_path)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic scoring for one system.")
    parser.add_argument("--system", choices=config.SYSTEMS, default="cira")
    parser.add_argument("--case", default=None, help="Score a single case id, e.g. 04-01")
    args = parser.parse_args()
    run(args.system, case_filter=args.case)


if __name__ == "__main__":
    main()
