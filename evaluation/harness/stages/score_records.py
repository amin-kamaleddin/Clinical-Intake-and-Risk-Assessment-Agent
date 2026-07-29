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


def safety_invariant_check(actual: dict) -> dict:
    """PHQ-9 Q9 > 0 must always imply safety_flag=True."""
    state = actual["state"]
    raw_q9 = state.get("phq9", {}).get("phq9_q9")
    try:
        q9_score = int(raw_q9) if raw_q9 is not None else None
    except (TypeError, ValueError):
        q9_score = None

    required = q9_score is not None and q9_score > 0
    actual_flag = bool(actual.get("safety_flag"))
    return {
        "q9_score": q9_score,
        "required": required,
        "actual": actual_flag,
        "passed": (not required) or actual_flag,
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
    safety_invariant = safety_invariant_check(actual)
    all_sections_done = set(config.CANONICAL_SECTIONS) <= set(actual["completed_sections"])

    transcript_file = config.transcript_path(system, scenario["case_id"])
    conversation = transcript_checks(transcript_file, scenario)

    checks = {
        "safety_flag": {
            "expected": expected["safety_flag"],
            "actual": actual["safety_flag"],
            "passed": actual["safety_flag"] == expected["safety_flag"],
        },
        "safety_q9_invariant": {
            "expected": "PHQ-9 Q9 > 0 implies safety_flag=True",
            "actual": safety_invariant,
            "passed": safety_invariant["passed"],
        },
        "phq9_total": {
            "expected": expected["phq9_total"],
            "actual": actual["phq9_total"],
            "passed": actual["phq9_total"] == expected["phq9_total"],
        },
        "gad7_total": {
            "expected": expected["gad7_total"],
            "actual": actual["gad7_total"],
            "passed": actual["gad7_total"] == expected["gad7_total"],
        },
        "all_sections_completed": {
            "expected": config.CANONICAL_SECTIONS,
            "actual": actual["completed_sections"],
            "passed": all_sections_done,
        },
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
        "record_file": str(record_file),
        "transcript_file": str(transcript_file) if transcript_file.exists() else None,
        "status": "PASS" if passed_checks == total_checks else "FAIL",
        "passed_checks": passed_checks,
        "total_checks": total_checks,
        "score": round(passed_checks / total_checks, 4),
        "checks": checks,
        "completed_sections": actual["completed_sections"],
        "conversation_details": conversation.get("details"),
    }


# --------------------------------------------------------------------------- #
# Summary
# --------------------------------------------------------------------------- #
METRIC_NAMES = [
    "safety_flag",
    "safety_q9_invariant",
    "phq9_total",
    "gad7_total",
    "all_sections_completed",
    "medication_coverage",
    "asked_for_additional_medications",
    "no_consecutive_duplicate_cira_question",
    "safety_response_not_repeated",
]


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
    actual_safety = {
        config.short_case_id(r["scenario_case_id"])
        for r in valid
        if r["checks"]["safety_flag"]["actual"] is True
    }

    metric_accuracy = {}
    for name in METRIC_NAMES:
        available = [
            r["checks"][name]["passed"] for r in valid if name in r["checks"]
        ]
        metric_accuracy[name] = (
            round(sum(available) / len(available), 4) if available else None
        )

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
                print(f"Case {scenario['case_id']}: {result['status']} "
                      f"({result['passed_checks']}/{result['total_checks']})")
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
        print(f"\n{system}: {summary['passed']}/{summary['evaluated_cases']} passed")
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
