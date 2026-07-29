"""Stage 4 - LLM-as-a-judge over both systems with one blinded rubric.

Reads the transcript + record artifacts each system produced and scores them
with the same judge, model, temperature, and weights. The system identity is
never shown to the judge.

Reads:   outputs/<system>/transcripts/case_XX.json
         outputs/<system>/records/case_XX.json
Writes:  outputs/judge/<system>/case_XX.json         (per-case judge output)
         outputs/reports/judge_comparison.json         (summary + paired diff)

Run directly::

    python -m harness.stages.run_judge
    python -m harness.stages.run_judge --case 04-01 --system cira
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import mean

from harness import config


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_scenarios(case_filter: str | None = None) -> list[dict]:
    scenarios = load_json(config.SCENARIO_FILE)
    if not isinstance(scenarios, list):
        raise ValueError("cira_scenarios.json must contain a list of scenarios.")
    if case_filter:
        scenarios = [s for s in scenarios if s.get("case_id") == case_filter]
        if not scenarios:
            raise ValueError(f"Scenario not found: {case_filter}")
    return scenarios


# --------------------------------------------------------------------------- #
# Judging
# --------------------------------------------------------------------------- #
def _judge_one(judge, scenario: dict, system: str) -> dict:
    """Judge a single case. Returns a report row (OK or ERROR); never raises."""
    from harness.llm_judge import save_judge_result

    case_id = scenario["case_id"]
    transcript_path = config.transcript_path(system, case_id)
    record_path = config.record_path(system, case_id)

    if not transcript_path.exists() or not record_path.exists():
        return {
            "system": system,
            "case_id": config.short_case_id(case_id),
            "scenario_case_id": case_id,
            "status": "ERROR",
            "error": "missing transcript or record artifact",
        }

    try:
        transcript = load_json(transcript_path)
        produced_record = load_json(record_path)
        # System identity is intentionally not passed to the judge.
        result = judge.evaluate(
            scenario=scenario,
            transcript=transcript,
            produced_record=produced_record,
        )
        result_path = config.judge_path(system, case_id)
        save_judge_result(result, result_path)
        return {
            **result.model_dump(),
            "system": system,
            "transcript_file": str(transcript_path),
            "record_file": str(record_path),
            "judge_result_file": str(result_path),
            "status": "OK",
        }
    except Exception as error:  # noqa: BLE001 - report and continue
        return {
            "system": system,
            "case_id": config.short_case_id(case_id),
            "scenario_case_id": case_id,
            "status": "ERROR",
            "error": str(error),
        }


def judge_system(judge, scenarios: list[dict], system: str) -> list[dict]:
    """Judge every scenario for one system, concurrently.

    A bounded thread pool means one stalled or slow case no longer blocks the
    others, and independent cases overlap. Each case has its own timeout inside
    the judge, so the pool cannot hang forever. Results are returned in scenario
    order regardless of completion order.
    """
    workers = max(1, min(config.JUDGE_MAX_WORKERS, len(scenarios)))
    report: list[dict] = [None] * len(scenarios)  # type: ignore[list-item]

    if workers == 1:
        for index, scenario in enumerate(scenarios):
            print(f"[{system}] Judging {scenario['case_id']}...")
            row = _judge_one(judge, scenario, system)
            report[index] = row
            _print_row(system, scenario["case_id"], row)
        return report

    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_index = {
            pool.submit(_judge_one, judge, scenario, system): index
            for index, scenario in enumerate(scenarios)
        }
        print(f"[{system}] Judging {len(scenarios)} cases "
              f"with {workers} workers...")
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            row = future.result()
            report[index] = row
            _print_row(system, scenarios[index]["case_id"], row)
    return report


def _print_row(system: str, case_id: str, row: dict) -> None:
    if row.get("status") == "OK":
        print(f"[{system}] {case_id}: "
              f"conversation={row['conversation_quality_score']:.3f} | "
              f"record={row['record_accuracy_score']:.3f}")
    else:
        print(f"[{system}] {case_id}: ERROR - {row.get('error')}")


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #
def average_subscores(cases: list[dict], group: str) -> dict[str, float] | None:
    ok = [c for c in cases if c.get("status") == "OK"]
    if not ok:
        return None
    names = ok[0][group].keys()
    return {name: round(mean(c[group][name] for c in ok), 4) for name in names}


def summarize_system(system: str, cases: list[dict]) -> dict:
    ok = [c for c in cases if c.get("status") == "OK"]
    return {
        "system": system,
        "evaluated_cases": len(ok),
        "error_cases": len(cases) - len(ok),
        "mean_conversation_quality_score": (
            round(mean(c["conversation_quality_score"] for c in ok), 4) if ok else None
        ),
        "mean_record_accuracy_score": (
            round(mean(c["record_accuracy_score"] for c in ok), 4) if ok else None
        ),
        "mean_conversation_subscores": average_subscores(ok, "conversation_subscores"),
        "mean_record_subscores": average_subscores(ok, "record_subscores"),
    }


def build_paired_comparison(all_cases: dict[str, list[dict]]) -> list[dict]:
    by_system = {
        system: {c["scenario_case_id"]: c for c in cases if c.get("status") == "OK"}
        for system, cases in all_cases.items()
    }
    if not by_system or any(not v for v in by_system.values()):
        return []
    common = sorted(set.intersection(*[set(v) for v in by_system.values()]))
    system_names = list(by_system)
    rows = []
    for case_id in common:
        row = {"scenario_case_id": case_id, "systems": {}}
        for system in system_names:
            case = by_system[system][case_id]
            row["systems"][system] = {
                "conversation_quality_score": case["conversation_quality_score"],
                "record_accuracy_score": case["record_accuracy_score"],
            }
        if len(system_names) == 2:
            first, second = system_names
            row["difference_second_minus_first"] = {
                "conversation_quality_score": round(
                    row["systems"][second]["conversation_quality_score"]
                    - row["systems"][first]["conversation_quality_score"], 4),
                "record_accuracy_score": round(
                    row["systems"][second]["record_accuracy_score"]
                    - row["systems"][first]["record_accuracy_score"], 4),
            }
        rows.append(row)
    return rows


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def run(systems=None, case_filter: str | None = None) -> dict:
    from harness.llm_judge import IntakeLLMJudge

    config.ensure_output_dirs()
    systems = list(systems) if systems else list(config.SYSTEMS)
    scenarios = load_scenarios(case_filter)

    judge = IntakeLLMJudge()
    all_cases = {system: judge_system(judge, scenarios, system) for system in systems}

    summaries = {s: summarize_system(s, cases) for s, cases in all_cases.items()}
    paired = build_paired_comparison(all_cases)

    report = {
        "judge_model": judge.model_name,
        "judge_temperature": config.JUDGE_TEMPERATURE,
        "evaluation_design": {
            "same_judge": True,
            "same_rubric": True,
            "system_identity_hidden_from_prompt": True,
            "paired_on_same_scenarios": True,
        },
        "systems": summaries,
        "paired_cases": paired,
        "cases": all_cases,
    }

    config.JUDGE_REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nSaved comparison report: {config.JUDGE_REPORT_PATH}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Judge intake systems with one rubric.")
    parser.add_argument("--system", action="append", choices=config.SYSTEMS,
                        help="Judge only this system (repeatable). Default: both.")
    parser.add_argument("--case", default=None, help="Judge a single case id, e.g. 04-01")
    args = parser.parse_args()
    run(systems=args.system, case_filter=args.case)


if __name__ == "__main__":
    main()
