import json
from pathlib import Path
from typing import Any


# ---------------------------------------------------------
# Paths
# ---------------------------------------------------------

EVALUATION_DIR = Path(__file__).resolve().parent

SCENARIO_FILE = EVALUATION_DIR / "cira_scenarios.json"
RECORDS_DIR = EVALUATION_DIR / "records"
RESULTS_DIR = EVALUATION_DIR / "results"
RESULT_FILE = RESULTS_DIR / "evaluation_report.json"


# ---------------------------------------------------------
# Loading
# ---------------------------------------------------------

def load_json(file_path: Path) -> Any:
    """Load a JSON file."""

    with file_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_scenarios() -> list[dict]:
    """Load all CIRA scenarios."""

    scenarios = load_json(SCENARIO_FILE)

    if not isinstance(scenarios, list):
        raise ValueError(
            "cira_scenarios.json must contain a JSON list."
        )

    return scenarios


def load_record_files() -> list[Path]:
    """Load all JSON record paths."""

    if not RECORDS_DIR.exists():
        raise FileNotFoundError(
            f"Records directory not found: {RECORDS_DIR}"
        )

    record_files = sorted(RECORDS_DIR.glob("*.json"))

    if not record_files:
        raise FileNotFoundError(
            f"No JSON records found in: {RECORDS_DIR}"
        )

    return record_files


# ---------------------------------------------------------
# Record matching
# ---------------------------------------------------------

def find_record_for_case(
    case_id: str,
    record_files: list[Path],
) -> Path | None:
    """
    Find the newest saved record for a case.

    Expected filename format:
    evaluation_04-01_c60072c6.json
    """

    prefix = f"evaluation_{case_id}_"

    matches = [
        record_file
        for record_file in record_files
        if record_file.name.startswith(prefix)
    ]

    if not matches:
        return None

    # Use the newest record if the same case was run more than once.
    return max(
        matches,
        key=lambda path: path.stat().st_mtime,
    )


# ---------------------------------------------------------
# Record extraction
# ---------------------------------------------------------

def unwrap_record(record: dict) -> dict:
    """
    Support either a direct CIRA state or a wrapped state.
    """

    for key in ("state", "final_state", "record", "data"):
        nested = record.get(key)

        if isinstance(nested, dict):
            return nested

    return record


def extract_actual_result(record: dict) -> dict:
    """Extract the values used in the evaluation."""

    state = unwrap_record(record)

    phq9 = state.get("phq9", {})
    gad7 = state.get("gad7", {})

    phq9_total = (
        phq9.get("phq9_total")
        if isinstance(phq9, dict)
        else None
    )

    gad7_total = (
        gad7.get("gad7_total")
        if isinstance(gad7, dict)
        else None
    )

    # Also support records that store totals at the top level.
    if phq9_total is None:
        phq9_total = state.get("phq9_total")

    if gad7_total is None:
        gad7_total = state.get("gad7_total")

    return {
        "safety_flag": state.get("safety_flag"),
        "phq9_total": phq9_total,
        "gad7_total": gad7_total,
        "completed_sections": state.get(
            "sections_completed",
            [],
        ),
    }


# ---------------------------------------------------------
# Evaluation
# ---------------------------------------------------------

def evaluate_case(
    scenario: dict,
    record_file: Path,
) -> dict:
    """Evaluate one saved CIRA record."""

    expected = scenario["expected_result"]
    record = load_json(record_file)
    actual = extract_actual_result(record)

    checks = {
        "safety_flag": {
            "expected": expected["safety_flag"],
            "actual": actual["safety_flag"],
            "passed": (
                actual["safety_flag"]
                == expected["safety_flag"]
            ),
        },
        "phq9_total": {
            "expected": expected["phq9_total"],
            "actual": actual["phq9_total"],
            "passed": (
                actual["phq9_total"]
                == expected["phq9_total"]
            ),
        },
        "gad7_total": {
            "expected": expected["gad7_total"],
            "actual": actual["gad7_total"],
            "passed": (
                actual["gad7_total"]
                == expected["gad7_total"]
            ),
        },
    }

    passed_checks = sum(
        check["passed"]
        for check in checks.values()
    )

    total_checks = len(checks)
    status = (
        "PASS"
        if passed_checks == total_checks
        else "FAIL"
    )

    return {
        "case_id": scenario["case_id"],
        "title": scenario["title"],
        "record_file": record_file.name,
        "status": status,
        "passed_checks": passed_checks,
        "total_checks": total_checks,
        "score": round(
            passed_checks / total_checks,
            4,
        ),
        "checks": checks,
        "completed_sections": actual[
            "completed_sections"
        ],
    }


def print_case_result(result: dict) -> None:
    """Print the detailed result for one case."""

    print()
    print("-" * 72)
    print(
        f"Case {result['case_id']}: "
        f"{result['title']}"
    )
    print("Record:", result["record_file"])
    print("Status:", result["status"])

    for check_name, check in result["checks"].items():
        check_status = (
            "PASS" if check["passed"] else "FAIL"
        )

        print(
            f"  {check_name}: {check_status} | "
            f"expected={check['expected']!r} | "
            f"actual={check['actual']!r}"
        )

    print(
        "  Score:",
        f"{result['passed_checks']}/"
        f"{result['total_checks']}",
    )


# ---------------------------------------------------------
# Reporting
# ---------------------------------------------------------

def build_summary(
    scenarios: list[dict],
    results: list[dict],
) -> dict:
    """Build the final evaluation summary."""

    valid_results = [
        result
        for result in results
        if result["status"] in {"PASS", "FAIL"}
    ]

    passed = sum(
        result["status"] == "PASS"
        for result in valid_results
    )

    failed = sum(
        result["status"] == "FAIL"
        for result in valid_results
    )

    errors = sum(
        result["status"] == "ERROR"
        for result in results
    )

    expected_safety_cases = {
        scenario["case_id"]
        for scenario in scenarios
        if scenario["expected_result"]["safety_flag"]
    }

    actual_safety_cases = {
        result["case_id"]
        for result in valid_results
        if result["checks"]["safety_flag"]["actual"]
        is True
    }

    missed_safety_cases = sorted(
        expected_safety_cases
        - actual_safety_cases
    )

    unexpected_safety_cases = sorted(
        actual_safety_cases
        - expected_safety_cases
    )

    evaluated_count = len(valid_results)

    safety_correct = sum(
        result["checks"]["safety_flag"]["passed"]
        for result in valid_results
    )

    phq9_correct = sum(
        result["checks"]["phq9_total"]["passed"]
        for result in valid_results
    )

    gad7_correct = sum(
        result["checks"]["gad7_total"]["passed"]
        for result in valid_results
    )

    return {
        "total_cases": len(scenarios),
        "evaluated_cases": evaluated_count,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "expected_safety_flags": len(
            expected_safety_cases
        ),
        "actual_safety_flags": len(
            actual_safety_cases
        ),
        "missed_safety_cases": missed_safety_cases,
        "unexpected_safety_cases": (
            unexpected_safety_cases
        ),
        "safety_accuracy": round(
            safety_correct / evaluated_count,
            4,
        )
        if evaluated_count
        else 0.0,
        "phq9_accuracy": round(
            phq9_correct / evaluated_count,
            4,
        )
        if evaluated_count
        else 0.0,
        "gad7_accuracy": round(
            gad7_correct / evaluated_count,
            4,
        )
        if evaluated_count
        else 0.0,
    }


def save_report(
    summary: dict,
    results: list[dict],
) -> Path:
    """Save one detailed JSON evaluation report."""

    RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    report = {
        "summary": summary,
        "cases": results,
    }

    with RESULT_FILE.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            report,
            file,
            indent=2,
            ensure_ascii=False,
        )

    return RESULT_FILE


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

def main() -> None:
    scenarios = load_scenarios()
    record_files = load_record_files()
    results = []

    print("=" * 72)
    print("CIRA RECORD EVALUATION")
    print("Scenarios:", len(scenarios))
    print("Records:", len(record_files))
    print("=" * 72)

    for scenario in scenarios:
        case_id = scenario["case_id"]

        record_file = find_record_for_case(
            case_id=case_id,
            record_files=record_files,
        )

        if record_file is None:
            result = {
                "case_id": case_id,
                "title": scenario["title"],
                "status": "ERROR",
                "error": (
                    "No matching record found for "
                    f"evaluation_{case_id}_*.json"
                ),
            }

            results.append(result)

            print()
            print(
                f"Case {case_id}: ERROR — "
                "no matching record found"
            )

            continue

        print(
            f"{case_id} -> {record_file.name}"
        )

        try:
            result = evaluate_case(
                scenario=scenario,
                record_file=record_file,
            )

            results.append(result)
            print_case_result(result)

        except Exception as error:
            result = {
                "case_id": case_id,
                "title": scenario["title"],
                "record_file": record_file.name,
                "status": "ERROR",
                "error": str(error),
            }

            results.append(result)

            print()
            print(
                f"Case {case_id}: ERROR — {error}"
            )

    summary = build_summary(
        scenarios=scenarios,
        results=results,
    )

    report_file = save_report(
        summary=summary,
        results=results,
    )

    print()
    print("=" * 72)
    print("FINAL EVALUATION SUMMARY")
    print("=" * 72)
    print("Total cases:", summary["total_cases"])
    print("Evaluated:", summary["evaluated_cases"])
    print("Passed:", summary["passed"])
    print("Failed:", summary["failed"])
    print("Errors:", summary["errors"])
    print()
    print(
        "Expected safety flags:",
        summary["expected_safety_flags"],
    )
    print(
        "Actual safety flags:",
        summary["actual_safety_flags"],
    )
    print(
        "Missed safety cases:",
        summary["missed_safety_cases"],
    )
    print(
        "Unexpected safety cases:",
        summary[
            "unexpected_safety_cases"
        ],
    )
    print()
    print(
        "Safety accuracy:",
        f"{summary['safety_accuracy']:.2%}",
    )
    print(
        "PHQ-9 accuracy:",
        f"{summary['phq9_accuracy']:.2%}",
    )
    print(
        "GAD-7 accuracy:",
        f"{summary['gad7_accuracy']:.2%}",
    )
    print()
    print("Report saved to:", report_file)
    print("=" * 72)


if __name__ == "__main__":
    main()
