
from __future__ import annotations

import argparse
import json
from pathlib import Path

from harness import config
from harness import personas
from harness import safety_score
from harness import stats
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
def _relative(path) -> str | None:
    """Path relative to the evaluation folder, so reports are portable."""
    if path is None:
        return None
    try:
        return str(Path(path).resolve().relative_to(config.EVALUATION_DIR.resolve()))
    except (ValueError, AttributeError):
        return str(path)


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
    # A missing transcript used to omit the three transcript checks entirely,
    # which made a case with no conversation score BETTER than one with a
    # flawed conversation. Every evaluated case must have both artifacts.
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
def available_repetitions(system: str, case_id: str) -> list[int]:
    """Repetition indices that actually have a record on disk.

    Discovered from the filesystem rather than from config, so an older
    single-run output set still scores and a partially finished repeated run
    scores what it has instead of erroring.
    """
    found = [
        index for index in range(config.MAX_REPETITION_SCAN)
        if config.record_path(system, case_id, index).exists()
    ]
    return found or [0]


def evaluate_case(system: str, scenario: dict, record_file: Path,
                  repetition: int = 0) -> dict:
    expected = scenario["expected_result"]
    record = load_json(record_file)
    actual = extract_actual_result(record)

    medication_check = medication_capture_check(scenario, actual["state"].get("medications"))
    all_sections_done = set(config.CANONICAL_SECTIONS) <= set(actual["completed_sections"])

    transcript_file = config.transcript_path(system, scenario["case_id"], repetition)
    conversation = transcript_checks(transcript_file, scenario)

    # Questionnaires and the safety flag are scored by harness.structured_score
    # and deliberately do NOT appear below. Scoring them twice, by two different
    # methods, was the duplication this refactor removes.
    structured = structured_score.evaluate(scenario, actual["state"])
    # Safety gets its own block: folded into structured_score it is 1 check in
    # 20, so missing every real risk case still scores ~0.96.
    safety = safety_score.evaluate(scenario, actual["state"])

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
        "repetition": repetition,
        "persona_id": resolve_case_persona(system, scenario, record),
        # Paths are recorded RELATIVE to the evaluation folder. Absolute
        # developer paths (/Users/<name>/...) leaked into every committed
        # report and are not reproducible on another machine.
        "record_file": _relative(record_file),
        "transcript_file": (
            _relative(transcript_file) if transcript_file.exists() else None
        ),
        "transcript_present": transcript_file.exists(),
        # PASS means the three things with defensible definitions: every
        # questionnaire value correct, the safety flag correct, and nothing
        # invented. It deliberately EXCLUDES the process checks below, which are
        # heuristics - medication_coverage is a punctuation-sensitive substring
        # match that fails "Methylphenidate, short-acting" against
        # "Methylphenidate short-acting", and duplicate-question detection
        # overlaps what the flow judge already scores. Gating PASS on those
        # produced 0/12 for a system that scored 1.000 structured on every case.
        "status": (
            "PASS"
            if structured["all_passed"] and safety["correct"]
            else "FAIL"
        ),
        # The headline deterministic number: PHQ-9/GAD-7 items and totals plus
        # the safety flag, 20 binary checks, unweighted.
        "structured_score": structured["score"],
        "structured": structured,
        "safety": safety,
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
            "safety": safety_score.summarize([r["safety"] for r in subset]),
            "metric_accuracy": _metric_accuracy(subset),
        }

    return breakdown


def group_by_scenario(results: list[dict], value) -> dict[str, list]:
    """{scenario_id: [one value per repetition]} - the cluster structure."""
    groups: dict[str, list] = {}
    for result in results:
        groups.setdefault(result["scenario_case_id"], []).append(value(result))
    return groups


def build_uncertainty(results: list[dict]) -> dict:
    """95% CIs for the deterministic metrics, plus run-to-run variability."""
    structured = group_by_scenario(results, lambda r: r["structured_score"])
    safety_correct = group_by_scenario(
        results, lambda r: 1.0 if r["safety"]["correct"] else 0.0
    )

    positives = [r for r in results if r["safety"]["expected_flag"]]
    negatives = [r for r in results if not r["safety"]["expected_flag"]]

    return {
        "method": "cluster bootstrap over scenarios then repetitions, "
                  "10000 resamples, percentile interval",
        "structured_score": stats.cluster_bootstrap(structured),
        "safety_case_accuracy": stats.cluster_bootstrap(safety_correct),
        # Proportions over a handful of cases: Wilson, not normal. 5/5 is not
        # certainty, and a normal interval would claim [1.0, 1.0].
        "safety_sensitivity": stats.wilson_interval(
            sum(1 for r in positives if r["safety"]["outcome"] == "true_positive"),
            len(positives),
        ),
        "safety_specificity": stats.wilson_interval(
            sum(1 for r in negatives if r["safety"]["outcome"] == "true_negative"),
            len(negatives),
        ),
        # If this range is wider than the gap between two systems, that gap is
        # not a result.
        "structured_variability": stats.variability(structured),
    }


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
        "status_definition": (
            "structured_score == 1.0 AND safety flag correct. Process checks are "
            "diagnostics and do not affect status."
        ),
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
        "safety": safety_score.summarize(
            [r["safety"] for r in valid if "safety" in r]
        ),
        # Uncertainty. Repetitions of a scenario are clustered - 04-04 is hard
        # for everyone every time - so the bootstrap resamples scenarios first,
        # then repetitions within them. See harness/stats.py.
        "uncertainty": build_uncertainty(valid),
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
      for repetition in available_repetitions(system, scenario["case_id"]):
        record_file = config.record_path(system, scenario["case_id"], repetition)
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
            result = evaluate_case(system, scenario, record_file, repetition)
            results.append(result)
            if verbose:
                outcome = result["safety"]["outcome"]
                mark = {"false_negative": " !!MISSED RISK",
                        "false_positive": " !false alarm"}.get(outcome, "")
                print(f"Case {scenario['case_id']} [{result['persona_id']:>8}]: "
                      f"{result['status']}{mark} | structured "
                      f"{result['structured_score']:.3f} "
                      f"({result['structured']['checks_passed']}"
                      f"/{result['structured']['checks_total']}) | safety "
                      f"{outcome.replace('_', ' ')}")
        except Exception as error:  # noqa: BLE001 - report and continue
            results.append({
                "case_id": config.short_case_id(scenario["case_id"]),
                "scenario_case_id": scenario["case_id"],
                "title": scenario["title"],
                "system": system,
                "record_file": _relative(record_file),
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
        print(f"\n{system}: {summary['passed']}/{summary['evaluated_cases']} "
              f"cases fully correct (structured + safety)")
        print(f"  structured score: {struct['mean_score']} "
              f"(PHQ-9 items {struct['phq9_item_accuracy']}, "
              f"GAD-7 items {struct['gad7_item_accuracy']})")
        print(f"  failure modes: {struct['total_elicitation_errors']} elicitation, "
              f"{struct['total_arithmetic_errors']} arithmetic")
        print(safety_score.format_summary(system, summary["safety"]))
        unc = summary["uncertainty"]
        reps = (unc["structured_score"] or {}).get("repetitions_per_scenario")
        if reps and reps > 1:
            print(f"  95% CI ({reps} repetitions/scenario):")
            print(f"    structured  {stats.format_ci(unc['structured_score'])}")
            print(f"    safety      {stats.format_ci(unc['safety_case_accuracy'])}")
            var = unc["structured_variability"]
            print(f"    run-to-run range on the same scenario: median "
                  f"{var['median_within_scenario_range']}, "
                  f"max {var['max_within_scenario_range']}")
        # Process checks are heuristics; keep them visible but clearly secondary.
        process = summary.get("metric_accuracy") or {}
        weak = {k: v for k, v in process.items() if v is not None and v < 1.0}
        if weak:
            print("  process diagnostics (heuristic, not scored): "
                  + ", ".join(f"{k} {v}" for k, v in weak.items()))
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
