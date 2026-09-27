

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import uuid
from pathlib import Path

from harness import config
from harness import personas
from harness import budget
from harness import provenance
from harness.patient_simulator import PatientSimulator


SYSTEM = "cira"

# Consecutive turns a section may make no progress before the driver gives up.
# Deliberately well below MAX_TURNS_PER_SECTION: nothing legitimate needs eight
# turns to move a single field forward.
STALL_LIMIT = int(os.getenv("CIRA_STALL_LIMIT", "8"))


def _import_cira():
    """Import the live CIRA package from the sibling cira/ folder.

    Returns (initial_state, graph, get_pending_fields, section_order) or raises
    ImportError with a clear message.
    """
    cira_dir = str(config.CIRA_DIR)
    if cira_dir not in sys.path:
        sys.path.insert(0, cira_dir)
    try:
        from core.state import REQUIRED_FIELDS, initial_state
        from graph.builder import graph
        from prompts.builder import get_pending_fields
    except ImportError as error:
        raise ImportError(
            f"Could not import the CIRA package from {config.CIRA_DIR}. "
            f"Original error: {error}"
        ) from error
    return initial_state, graph, get_pending_fields, list(REQUIRED_FIELDS.keys())


def load_scenarios(case_filter: str | None = None) -> list[dict]:
    scenarios = json.loads(config.SCENARIO_FILE.read_text(encoding="utf-8"))
    if not isinstance(scenarios, list):
        raise ValueError("cira_scenarios.json must contain a list.")
    if case_filter:
        scenarios = [s for s in scenarios if s.get("case_id") == case_filter]
        if not scenarios:
            raise ValueError(f"Scenario not found: {case_filter}")
    return scenarios


def get_message_text(message) -> str:
    if isinstance(message, dict):
        return str(message.get("content", ""))
    return str(message.content)


def create_cira_state(initial_state: dict, case_id: str) -> dict:
    state = copy.deepcopy(initial_state)
    state["session_id"] = f"evaluation_{case_id}_{uuid.uuid4().hex[:8]}"
    state["case_id"] = config.short_case_id(case_id)
    state["scenario_case_id"] = case_id
    state["current_section"] = "general_information"
    state["messages"] = []
    # The intake is conducted in this language; the RECORD is still written in
    # English (see cira/prompts/static_prompt.py), which is what lets record
    # scoring and the judges run unchanged across languages.
    state["preferred_language"] = config.LANGUAGE
    return state


def run_case(
    scenario,
    initial_state,
    graph,
    get_pending_fields,
    section_order,
    persona=None,
    repetition: int = 0,
) -> None:
    case_id = scenario["case_id"]
    persona = personas.get_persona(persona)
    print("\n" + "=" * 70)
    print("Case:", case_id, "-", scenario["title"])
    print("Patient persona:", f"{persona.id} ({persona.label})"
          + (f"   repetition {repetition}" if repetition else ""))
    print("=" * 70)

    patient = PatientSimulator(scenario, persona=persona, repetition=repetition)
    transcript: list[dict] = []
    cira_state = create_cira_state(initial_state, case_id)
    safety_reported = False

    # Artifacts are written after EVERY section and again in a finally block,
    # not only once at the end of the case. A single end-of-case save meant an
    # interrupted run (^C) or one exception left nothing on disk at all - a
    # forty-minute run could produce zero scoreable output. Partial artifacts
    # are far more useful than none: the scorer reports the sections that did
    # complete and flags the rest.
    # graph.invoke() RETURNS a new state rather than mutating the one passed in,
    # so _run_sections must hand the latest state back out. A plain parameter
    # cannot: rebinding the name inside the function leaves this frame pointing
    # at the pre-run dict, and the finally block below would then save it.
    #
    # That is not a hypothetical. Nested section dicts survived it because
    # LangGraph passes them by reference and the node mutates them in place, and
    # sections_completed survived because it is appended in place - so records
    # looked complete. Top-level SCALARS did not: safety_flag was set to True on
    # LangGraph's copy and the saved record kept the initial False. Every real
    # risk case was written out unflagged while the transcript showed the safety
    # message being delivered.
    state_box = {"state": cira_state}
    try:
        _run_sections(
            scenario, transcript, state_box, graph,
            get_pending_fields, section_order, patient, safety_reported,
            repetition=repetition,
        )
    finally:
        _save_artifacts(scenario, transcript, state_box["state"], patient, repetition=repetition)


def _run_sections(scenario, transcript, state_box, graph, get_pending_fields,
                  section_order, patient, safety_reported,
                  repetition: int = 0) -> None:
    cira_state = state_box["state"]
    for section in section_order:
        print(f"\n{'-' * 70}\nSection: {section}\n{'-' * 70}")
        # Refresh the persona's per-section hedge budget.
        patient.begin_section(section)
        cira_state["current_section"] = section
        cira_state["messages"] = []
        cira_state = graph.invoke(cira_state)
        state_box["state"] = cira_state

        pending_fields = get_pending_fields(cira_state, section)
        if not pending_fields:
            print(section, "already complete.")
            continue

        cira_question = get_message_text(cira_state["messages"][-1])

        # Stall detection. A section that makes no progress for several turns is
        # livelocked, not slow: the agent believes it is finished while a field
        # is still pending, so the driver keeps feeding it turns and the same
        # exchange repeats until the turn cap. Breaking out with a loud error
        # costs one wasted section instead of burning the cap on every case, and
        # names the field responsible so the cause is visible.
        stalled_turns = 0
        previous_pending = set(pending_fields)
        # Snapshot the section's VALUES too. The pending set alone is not a
        # progress signal: collecting dose, start date and side effects all
        # writes into the same repeatable field, so the set stays frozen while
        # the interview is working perfectly. Counting those as stalled turns
        # killed the medications section one turn before it asked about past
        # medications.
        previous_values = dict(cira_state.get(section) or {})

        for turn_number in range(1, config.MAX_TURNS_PER_SECTION + 1):
            if not cira_question.strip():
                # Don't abandon the section on one empty turn - nudge and let the
                # stall counter decide. Abandoning immediately cost a whole
                # section (and self_harm_details) on the active-risk case.
                print(f"WARNING: empty question in '{section}' "
                      f"(pending {pending_fields}); nudging")
                # Never render a questionnaire item key into patient-facing
                # text: "gad7_q1" becomes "gad7 q1", and the simulator's
                # bare-question-number pattern matched the "q1", resolving a
                # GAD-7 item to phq9_q1.
                first = pending_fields[0] if pending_fields else ""
                if first.startswith(("phq9_", "gad7_")):
                    cira_question = (
                        "Could you choose one of the options above for that question?"
                    )
                elif pending_fields:
                    cira_question = (
                        f"Could you tell me about {first.replace('_', ' ')}?"
                    )
                else:
                    cira_question = "Is there anything else you would like to add?"

            print("\nCIRA:", cira_question)
            transcript.append({
                "section": section, "turn": turn_number,
                "speaker": "CIRA", "message": cira_question,
            })

            patient_answer = patient.answer(cira_question)
            print("PATIENT:", patient_answer)
            transcript.append({
                "section": section, "turn": turn_number,
                "speaker": "PATIENT", "message": patient_answer,
            })

            cira_state["messages"] = list(cira_state["messages"]) + [
                {"role": "user", "content": patient_answer}
            ]
            cira_state = graph.invoke(cira_state)
            state_box["state"] = cira_state

            if cira_state.get("safety_flag") and not safety_reported:
                print("Safety flag raised. Continuing the intake.")
                safety_reported = True

            pending_fields = get_pending_fields(cira_state, section)
            if not pending_fields:
                print(section, "completed.")
                break

            current_values = dict(cira_state.get(section) or {})
            made_progress = (
                set(pending_fields) != previous_pending
                or current_values != previous_values
            )
            if made_progress:
                stalled_turns = 0
                previous_pending = set(pending_fields)
                previous_values = current_values
            else:
                stalled_turns += 1

            if stalled_turns >= STALL_LIMIT:
                print(
                    f"ERROR: section '{section}' stalled for {STALL_LIMIT} turns "
                    f"with no progress on {pending_fields}. Abandoning the section."
                )
                break

            cira_question = get_message_text(cira_state["messages"][-1])
        else:
            print(f"ERROR: section '{section}' exceeded "
                  f"{config.MAX_TURNS_PER_SECTION} turns.")

        # Checkpoint: everything collected so far survives an interruption.
        _save_artifacts(scenario, transcript, cira_state, patient, quiet=True,
                        repetition=repetition)


def _build_record(scenario: dict, cira_state: dict, patient=None) -> dict:
    """Assemble the saved record from clinical state only.

    The record mirrors the scenario ``patient_facts`` layout: the 12 canonical
    intake sections as nested dicts, plus the evaluation-relevant flags and
    identifiers. Conversation and runtime state (``messages``, ``session_id``,
    ``current_section``, ``conversation_started``, ...) are deliberately
    excluded, so no LangChain messages or tool calls ever reach the record.
    """
    record = {
        "case_id": config.short_case_id(scenario["case_id"]),
        "scenario_case_id": scenario["case_id"],
        "title": scenario["title"],
        "system": SYSTEM,
        # False when the case was interrupted or a section was abandoned, so a
        # partial record is never mistaken for a clean one.
        "intake_complete": set(config.CANONICAL_SECTIONS)
        <= set(cira_state.get("sections_completed", [])),
        "run_id": provenance.current_run_id(),
        # Which patient style produced this record. Stamped here (not just in
        # the report) so a record file is self-describing and can be stratified
        # by persona long after the run.
        "persona_id": patient.persona.id if patient else None,
        "safety_flag": cira_state.get("safety_flag"),
        "sections_completed": cira_state.get("sections_completed", []),
    }
    for section in config.CANONICAL_SECTIONS:
        if section in cira_state:
            record[section] = cira_state[section]
    return record


def _clean_conversation(transcript: list[dict]) -> list[dict]:
    """Keep only real dialogue turns (non-empty CIRA/PATIENT text)."""
    return [
        turn
        for turn in transcript
        if turn.get("speaker") in ("CIRA", "PATIENT")
        and isinstance(turn.get("message"), str)
        and turn["message"].strip()
    ]


def _save_artifacts(
    scenario: dict, transcript: list[dict], cira_state: dict, patient=None,
    quiet: bool = False, repetition: int = 0,
) -> None:
    case_id = scenario["case_id"]

    transcript_payload = {
        "case_id": config.short_case_id(case_id),
        "scenario_case_id": case_id,
        "title": scenario["title"],
        "system": SYSTEM,
        "run_id": provenance.current_run_id(),
        "repetition": repetition,
        "persona_id": patient.persona.id if patient else None,
        "patient_behaviour": patient.behaviour_summary() if patient else None,
        "budget": budget.measure(_clean_conversation(transcript)),
        "conversation": _clean_conversation(transcript),
        "final_result": {
            "safety_flag": cira_state.get("safety_flag"),
            "phq9_total": cira_state.get("phq9", {}).get("phq9_total"),
            "gad7_total": cira_state.get("gad7", {}).get("gad7_total"),
            "completed_sections": cira_state.get("sections_completed", []),
            "medications": cira_state.get("medications", {}),
        },
    }

    record_payload = _build_record(scenario, cira_state, patient)
    record_payload["repetition"] = repetition

    config.transcript_path(SYSTEM, case_id, repetition).write_text(
        json.dumps(transcript_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    config.record_path(SYSTEM, case_id, repetition).write_text(
        json.dumps(record_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if not quiet:
        completed = len(cira_state.get("sections_completed", []))
        print(f"Saved transcript + record for {case_id} "
              f"({completed}/{len(config.CANONICAL_SECTIONS)} sections complete)")


def run(
    case_filter: str | None = None,
    persona_override: str | None = None,
    persona_seed: int | None = None,
    persona_strategy: str | None = None,
    repetitions: int | None = None,
) -> None:
    config.ensure_output_dirs()
    initial_state, graph, get_pending_fields, section_order = _import_cira()
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
    print("LIVE CIRA EVALUATION")
    print("Scenarios:", len(scenarios))
    print("=" * 70)

    for repetition in config.repetition_indices(repetitions):
        for scenario in scenarios:
            try:
                run_case(
                    scenario,
                    initial_state,
                    graph,
                    get_pending_fields,
                    section_order,
                    persona=assignment.get(scenario["case_id"]),
                    repetition=repetition,
                )
            except Exception as error:  # noqa: BLE001 - report and continue
                print(f"ERROR while running {scenario['case_id']} "
                      f"rep {repetition}: {error}")

    print("\nCIRA artifacts written under:", config._system_dir(SYSTEM))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the live CIRA agent.")
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