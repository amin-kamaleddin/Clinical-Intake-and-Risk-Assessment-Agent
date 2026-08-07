"""Stage 2 - run the deterministic rule-based baseline over the scenarios.

Produces raw artifacts only (transcript + record). Deterministic scoring is done
uniformly for every system by ``harness.stages.score_records``, so this driver
no longer computes or writes its own report.

Writes:  outputs/rule_based/transcripts/case_XX.json
         outputs/rule_based/records/case_XX.json

Run directly::

    python -m harness.stages.run_rule_based
    python -m harness.stages.run_rule_based --case 04-01
"""

from __future__ import annotations

import argparse
import json

from harness import config
from harness import personas
from harness.patient_simulator import PatientSimulator
from harness.rule_based_cira import RuleBasedCIRA


SYSTEM = "rule_based"


def load_scenarios(case_filter: str | None = None) -> list[dict]:
    scenarios = json.loads(config.SCENARIO_FILE.read_text(encoding="utf-8"))
    if not isinstance(scenarios, list):
        raise ValueError("cira_scenarios.json must contain a list.")
    if case_filter:
        scenarios = [s for s in scenarios if s.get("case_id") == case_filter]
        if not scenarios:
            raise ValueError(f"Scenario not found: {case_filter}")
    return scenarios


def run_case(scenario: dict, persona=None) -> None:
    case_id = scenario["case_id"]
    persona = personas.get_persona(persona)
    print(f"\n{'=' * 70}\nRule-based: {case_id} - {scenario.get('title', '')}")
    print(f"Patient persona: {persona.id} ({persona.label})\n{'=' * 70}")

    patient = PatientSimulator(scenario, persona=persona)
    engine = RuleBasedCIRA()

    def answer(question: str) -> str:
        print("RULE SYSTEM:", question)
        patient_answer = patient.answer(question)
        print("PATIENT:", patient_answer)
        return patient_answer

    result = engine.run(answer)

    transcript_payload = {
        "case_id": config.short_case_id(case_id),
        "scenario_case_id": case_id,
        "title": scenario.get("title", ""),
        "system": SYSTEM,
        "persona_id": persona.id,
        "patient_behaviour": patient.behaviour_summary(),
        "conversation": result.transcript,
        "final_result": {
            "safety_flag": result.safety_flag,
            "phq9_total": result.record["phq9"].get("phq9_total"),
            "gad7_total": result.record["gad7"].get("gad7_total"),
            "completed_sections": result.completed_sections,
            "safety_reasons": result.safety_reasons,
        },
    }

    record_payload = dict(result.record)
    record_payload.update({
        "case_id": config.short_case_id(case_id),
        "scenario_case_id": case_id,
        "system": SYSTEM,
        "persona_id": persona.id,
        "safety_reasons": result.safety_reasons,
        "issues": result.issues,
    })

    config.transcript_path(SYSTEM, case_id).write_text(
        json.dumps(transcript_payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    config.record_path(SYSTEM, case_id).write_text(
        json.dumps(record_payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Saved transcript + record for {case_id}")


def run(
    case_filter: str | None = None,
    persona_override: str | None = None,
    persona_seed: int | None = None,
    persona_strategy: str | None = None,
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
    print("RULE-BASED BASELINE")
    print("Scenarios:", len(scenarios))
    print("=" * 70)

    for scenario in scenarios:
        try:
            run_case(scenario, persona=assignment.get(scenario["case_id"]))
        except Exception as error:  # noqa: BLE001 - report and continue
            print(f"ERROR while running {scenario['case_id']}: {error}")

    print("\nRule-based artifacts written under:", config._system_dir(SYSTEM))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the rule-based baseline.")
    parser.add_argument("--case", default=None, help="Run a single case id, e.g. 04-01")
    parser.add_argument("--persona", choices=personas.PERSONA_IDS, default=None,
                        help="Force this persona onto every case.")
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
    )


if __name__ == "__main__":
    main()
