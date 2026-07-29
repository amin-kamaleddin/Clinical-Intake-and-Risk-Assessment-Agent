"""Stage - run the naive single-LLM baseline over the scenarios (ablation).

Same patient simulator, same scenarios, same output schema as the other
systems; the only difference from CIRA is the absence of architecture (one
prompt + a plain chat loop + one extraction call). Produces artifacts only;
scoring and judging happen uniformly downstream.

Writes:  outputs/naive_llm/transcripts/case_XX.json
         outputs/naive_llm/records/case_XX.json

Run directly::

    python -m harness.stages.run_naive
    python -m harness.stages.run_naive --case 04-01
"""

from __future__ import annotations

import argparse
import json

from harness import config
from harness.patient_simulator import PatientSimulator


SYSTEM = "naive_llm"


def load_scenarios(case_filter: str | None = None) -> list[dict]:
    scenarios = json.loads(config.SCENARIO_FILE.read_text(encoding="utf-8"))
    if not isinstance(scenarios, list):
        raise ValueError("cira_scenarios.json must contain a list.")
    if case_filter:
        scenarios = [s for s in scenarios if s.get("case_id") == case_filter]
        if not scenarios:
            raise ValueError(f"Scenario not found: {case_filter}")
    return scenarios


def derive_sections_completed(record: dict) -> list[str]:
    """A section counts as completed if it holds any non-null value.

    This is bookkeeping, not intake behaviour, so deriving it mechanically keeps
    the comparison fair: a section the naive intake never touched stays empty and
    is not marked complete.
    """
    completed = []
    for section in config.CANONICAL_SECTIONS:
        data = record.get(section)
        if isinstance(data, dict) and any(v is not None for v in data.values()):
            completed.append(section)
    return completed


def run_case(scenario: dict) -> None:
    from harness.naive_llm import NaiveLLMIntake

    case_id = scenario["case_id"]
    print(f"\n{'=' * 70}\nNaive LLM: {case_id} - {scenario.get('title', '')}\n{'=' * 70}")

    patient = PatientSimulator(scenario)
    engine = NaiveLLMIntake()
    transcript, record = engine.run(patient)

    record["case_id"] = config.short_case_id(case_id)
    record["scenario_case_id"] = case_id
    record["system"] = SYSTEM
    record["sections_completed"] = derive_sections_completed(record)

    transcript_payload = {
        "case_id": config.short_case_id(case_id),
        "scenario_case_id": case_id,
        "title": scenario.get("title", ""),
        "system": SYSTEM,
        "conversation": transcript,
        "final_result": {
            "safety_flag": record.get("safety_flag"),
            "phq9_total": record.get("phq9", {}).get("phq9_total"),
            "gad7_total": record.get("gad7", {}).get("gad7_total"),
            "completed_sections": record["sections_completed"],
        },
    }

    config.transcript_path(SYSTEM, case_id).write_text(
        json.dumps(transcript_payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    config.record_path(SYSTEM, case_id).write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Saved transcript ({len(transcript)} turns) + record for {case_id}")


def run(case_filter: str | None = None) -> None:
    config.ensure_output_dirs()
    scenarios = load_scenarios(case_filter)

    print("=" * 70)
    print("NAIVE LLM BASELINE")
    print("Model:", config.NAIVE_MODEL_NAME)
    print("Scenarios:", len(scenarios))
    print("=" * 70)

    for scenario in scenarios:
        try:
            run_case(scenario)
        except Exception as error:  # noqa: BLE001 - report and continue
            print(f"ERROR while running {scenario['case_id']}: {error}")

    print("\nNaive-LLM artifacts written under:", config._system_dir(SYSTEM))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the naive LLM baseline.")
    parser.add_argument("--case", default=None, help="Run a single case id, e.g. 04-01")
    args = parser.parse_args()
    run(case_filter=args.case)


if __name__ == "__main__":
    main()
