
from __future__ import annotations

import argparse
import json

from harness import config
from harness import personas
from harness import provenance
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
    """A section is complete when every APPLICABLE field is filled.

    "Any non-null value" was not the same rule CIRA is held to. CIRA requires
    every applicable field before a section closes; marking a naive section
    complete on one filled field out of eleven inflated its completion rate and
    made the comparison unfair in the naive arm's favour.

    Applicable means: skip fields hidden by their controlling boolean, exactly
    as ``prompts.builder.get_pending_fields`` does for CIRA.
    """
    completed = []
    for section in config.CANONICAL_SECTIONS:
        data = record.get(section)
        if not isinstance(data, dict) or not data:
            continue

        pending = False
        for field, value in data.items():
            if value is not None:
                continue
            dependency = config.CONDITIONAL_FIELDS.get(field)
            if dependency:
                parent, hidden_value = dependency
                if data.get(parent) is hidden_value:
                    continue      # correctly skipped, not missing
            pending = True
            break

        if not pending:
            completed.append(section)
    return completed


def run_case(scenario: dict, persona=None, repetition: int = 0) -> None:
    from harness.naive_llm import NaiveLLMIntake

    case_id = scenario["case_id"]
    persona = personas.get_persona(persona)
    print(f"\n{'=' * 70}\nNaive LLM: {case_id} - {scenario.get('title', '')}")
    print(f"Patient persona: {persona.id} ({persona.label})"
          + (f"   repetition {repetition}" if repetition else "")
          + f"\n{'=' * 70}")

    patient = PatientSimulator(scenario, persona=persona, repetition=repetition)
    engine = NaiveLLMIntake()
    transcript, record = engine.run(patient)

    record["case_id"] = config.short_case_id(case_id)
    record["scenario_case_id"] = case_id
    record["system"] = SYSTEM
    record["persona_id"] = persona.id
    record["run_id"] = provenance.current_run_id()
    record["repetition"] = repetition
    record["sections_completed"] = derive_sections_completed(record)

    transcript_payload = {
        "case_id": config.short_case_id(case_id),
        "scenario_case_id": case_id,
        "title": scenario.get("title", ""),
        "system": SYSTEM,
        "run_id": provenance.current_run_id(),
        "repetition": repetition,
        "persona_id": persona.id,
        "patient_behaviour": patient.behaviour_summary(),
        "conversation": transcript,
        "final_result": {
            "safety_flag": record.get("safety_flag"),
            "phq9_total": record.get("phq9", {}).get("phq9_total"),
            "gad7_total": record.get("gad7", {}).get("gad7_total"),
            "completed_sections": record["sections_completed"],
        },
    }

    config.transcript_path(SYSTEM, case_id, repetition).write_text(
        json.dumps(transcript_payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    config.record_path(SYSTEM, case_id, repetition).write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Saved transcript ({len(transcript)} turns) + record for {case_id}")


def run(
    case_filter: str | None = None,
    persona_override: str | None = None,
    persona_seed: int | None = None,
    persona_strategy: str | None = None,
    repetitions: int | None = None,
) -> None:
    config.ensure_output_dirs()
    scenarios = load_scenarios(case_filter)

    # Resolved from the full scenario file, so a --case run uses the same
    # persona the case would get in a full run, and so every system faces the
    # identical patient on the identical case.
    assignment = personas.resolve_assignment(
        seed=persona_seed,
        strategy=persona_strategy,
        override=persona_override or config.PERSONA_OVERRIDE,
    )

    print("=" * 70)
    print("NAIVE LLM BASELINE")
    print("Model:", config.NAIVE_MODEL_NAME)
    print("Scenarios:", len(scenarios))
    print("=" * 70)

    for repetition in config.repetition_indices(repetitions):
        for scenario in scenarios:
            try:
                run_case(
                    scenario,
                    persona=assignment.get(scenario["case_id"]),
                    repetition=repetition,
                )
            except Exception as error:  # noqa: BLE001 - report and continue
                print(f"ERROR while running {scenario['case_id']} "
                      f"rep {repetition}: {error}")

    print("\nNaive-LLM artifacts written under:", config._system_dir(SYSTEM))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the naive LLM baseline.")
    parser.add_argument("--case", default=None, help="Run a single case id, e.g. 04-01")
    parser.add_argument("--persona", choices=personas.PERSONA_IDS, default=None,
                        help="Force this persona onto every case.")
    parser.add_argument("--repetitions", type=int, default=None,
                        help="Independent interactions per scenario (default 1).")
    parser.add_argument("--persona-seed", type=int, default=None,
                        help="Seed for the persona assignment.")
    parser.add_argument("--persona-strategy",
                        choices=personas.ASSIGNMENT_STRATEGIES, default=None)
    args = parser.parse_args()
    run(
        case_filter=args.case,
        persona_override=args.persona,
        persona_seed=args.persona_seed,
        persona_strategy=args.persona_strategy,
        repetitions=args.repetitions,
    )


if __name__ == "__main__":
    main()
