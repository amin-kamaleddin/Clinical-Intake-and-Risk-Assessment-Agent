import copy
import json
import sys
import uuid
from pathlib import Path
from langchain_core.messages import HumanMessage

# Project folders
PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVALUATION_DIR = PROJECT_ROOT / "evaluation"
CIRA_DIR = PROJECT_ROOT / "cira"
MAX_TURNS_PER_SECTION = 30
sys.path.insert(0, str(CIRA_DIR))


from core.state import REQUIRED_FIELDS, initial_state
from graph.builder import graph
from prompts.builder import get_pending_fields

from patient_simulator import PatientSimulator

SECTION_ORDER = list(REQUIRED_FIELDS.keys())
TRANSCRIPT_DIR = EVALUATION_DIR / "transcripts"


SCENARIO_FILE = (
    EVALUATION_DIR
    / "cira_scenarios.json"
)


def load_scenarios() -> list[dict]:
    with SCENARIO_FILE.open(
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


def get_message_text(message) -> str:
    """
    Get text from either a LangChain message
    or a normal Python dictionary.
    """

    if isinstance(message, dict):
        return str(message.get("content", ""))

    return str(message.content)

def create_cira_state(case_id: str) -> dict:
    """
    Create a fresh CIRA state for one test patient.
    """

    state = copy.deepcopy(initial_state)

    state["session_id"] = (
        f"evaluation_{case_id}_"
        f"{uuid.uuid4().hex[:8]}"
    )

    state["current_section"] = "general_information"
    state["messages"] = []

    return state


# def main():
#     scenarios = load_scenarios()

#     # Continue testing only the first case.
#     scenario = scenarios[0]

#     print("Case:", scenario["case_id"])
#     print("Title:", scenario["title"])

#     # Create the simulated patient.
#     patient = PatientSimulator(scenario)

#     # Create a fresh CIRA session.
#     cira_state = create_cira_state(
#         scenario["case_id"]
#     )

#     # Invoke CIRA without a patient message.
#     # CIRA should ask the first question.
#     cira_state = graph.invoke(cira_state)

#     last_message = cira_state["messages"][-1]
#     cira_question = get_message_text(last_message)

#     print()
#     print("CIRA:", cira_question)

#         # Send CIRA's question to the simulated patient.
#     patient_answer = patient.answer(cira_question)

#     print("PATIENT:", patient_answer)

#     # Add the patient's answer to CIRA's conversation state.
#     cira_state["messages"] = list(cira_state["messages"]) + [
#         {
#             "role": "user",
#             "content": patient_answer,
#         }
#     ]


#     cira_state = graph.invoke(cira_state)

#     next_message = cira_state["messages"][-1]
#     next_cira_question = get_message_text(next_message)

#     print()
#     print("CIRA:", next_cira_question)



def save_transcript(
    scenario: dict,
    transcript: list[dict],
    cira_state: dict,
) -> Path:
    """Save the complete conversation for one scenario."""

    TRANSCRIPT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    clean_case_id = scenario["case_id"].replace("-", "_")

    output_file = (
        TRANSCRIPT_DIR
        / f"case_{clean_case_id}.json"
    )

    transcript_data = {
        "case_id": scenario["case_id"],
        "title": scenario["title"],
        "conversation": transcript,
        "final_result": {
            "safety_flag": cira_state["safety_flag"],
            "phq9_total": cira_state["phq9"]["phq9_total"],
            "gad7_total": cira_state["gad7"]["gad7_total"],
            "completed_sections": cira_state[
                "sections_completed"
            ],
        },
    }

    with output_file.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            transcript_data,
            file,
            indent=2,
            ensure_ascii=False,
        )

    return output_file


def create_case_result(
    scenario: dict,
    cira_state: dict,
    transcript_file: Path,
    issues: list[str],
) -> dict:
    """Compare CIRA's result with the expected scenario result."""

    expected = scenario["expected_result"]

    actual = {
        "safety_flag": cira_state["safety_flag"],
        "phq9_total": cira_state["phq9"]["phq9_total"],
        "gad7_total": cira_state["gad7"]["gad7_total"],
        "completed_sections": cira_state[
            "sections_completed"
        ],
    }

    checks = {
        "safety_flag": (
            actual["safety_flag"]
            == expected["safety_flag"]
        ),
        "phq9_total": (
            actual["phq9_total"]
            == expected["phq9_total"]
        ),
        "gad7_total": (
            actual["gad7_total"]
            == expected["gad7_total"]
        ),
        "all_sections_completed": (
            set(SECTION_ORDER)
            <= set(actual["completed_sections"])
        ),
    }

    passed = all(checks.values()) and not issues

    return {
        "case_id": scenario["case_id"],
        "title": scenario["title"],
        "expected": expected,
        "actual": actual,
        "checks": checks,
        "issues": issues,
        "status": "PASS" if passed else "FAIL",
        "transcript_file": str(transcript_file),
    }


def run_case(scenario: dict) -> dict:
    """Run one complete CIRA scenario."""

    print()
    print("=" * 70)
    print("Case:", scenario["case_id"])
    print("Title:", scenario["title"])
    print("=" * 70)

    patient = PatientSimulator(scenario)
    transcript = []
    issues = []

    cira_state = create_cira_state(
        scenario["case_id"]
    )

    safety_reported = False

    for section in SECTION_ORDER:
        print()
        print("-" * 70)
        print("Starting section:", section)
        print("-" * 70)

        cira_state["current_section"] = section
        cira_state["messages"] = []

        # Make CIRA ask the first question.
        cira_state = graph.invoke(cira_state)

        pending_fields = get_pending_fields(
            cira_state,
            section,
        )

        # The section may already be complete.
        if not pending_fields:
            print(section, "was already complete.")
            continue

        last_message = cira_state["messages"][-1]
        cira_question = get_message_text(last_message)

        for turn_number in range(
            1,
            MAX_TURNS_PER_SECTION + 1,
        ):
            if not cira_question.strip():
                issue = (
                    f"CIRA returned an empty question "
                    f"in section '{section}'. "
                    f"Pending fields: {pending_fields}"
                )

                print("ERROR:", issue)
                issues.append(issue)
                break

            print()
            print("CIRA:", cira_question)

            transcript.append(
                {
                    "section": section,
                    "turn": turn_number,
                    "speaker": "CIRA",
                    "message": cira_question,
                }
            )

            patient_answer = patient.answer(
                cira_question
            )

            print("PATIENT:", patient_answer)

            transcript.append(
                {
                    "section": section,
                    "turn": turn_number,
                    "speaker": "PATIENT",
                    "message": patient_answer,
                }
            )

            # Send the patient's answer to CIRA.
            cira_state["messages"] = list(
                cira_state["messages"]
            ) + [
                {
                    "role": "user",
                    "content": patient_answer,
                }
            ]

            cira_state = graph.invoke(cira_state)

            # Report safety once, but continue.
            if (
                cira_state["safety_flag"]
                and not safety_reported
            ):
                print()
                print(
                    "Safety flag raised. "
                    "Continuing the intake."
                )

                safety_reported = True

            pending_fields = get_pending_fields(
                cira_state,
                section,
            )

            print("Pending fields:", pending_fields)

            if not pending_fields:
                print()
                print(section, "completed.")
                break

            last_message = cira_state["messages"][-1]

            cira_question = get_message_text(
                last_message
            )

        else:
            issue = (
                f"Section '{section}' exceeded "
                f"{MAX_TURNS_PER_SECTION} turns."
            )

            print("ERROR:", issue)
            issues.append(issue)

    transcript_file = save_transcript(
        scenario=scenario,
        transcript=transcript,
        cira_state=cira_state,
    )

    result = create_case_result(
        scenario=scenario,
        cira_state=cira_state,
        transcript_file=transcript_file,
        issues=issues,
    )

    print()
    print("Case result:", result["status"])
    print("Transcript:", transcript_file)

    return result


def main():
    scenarios = load_scenarios()
    results = []

    print("=" * 70)
    print("CIRA AUTOMATED EVALUATION")
    print("Number of scenarios:", len(scenarios))
    print("=" * 70)

    for scenario in scenarios:
        try:
            result = run_case(scenario)
            results.append(result)

        except Exception as error:
            print()
            print(
                f"ERROR while running "
                f"{scenario['case_id']}: {error}"
            )

            results.append(
                {
                    "case_id": scenario["case_id"],
                    "title": scenario["title"],
                    "status": "ERROR",
                    "error": str(error),
                }
            )




    passed = sum(
        result["status"] == "PASS"
        for result in results
    )

    failed = sum(
        result["status"] == "FAIL"
        for result in results
    )

    errors = sum(
        result["status"] == "ERROR"
        for result in results
    )

    print()
    print("=" * 70)
    print("EVALUATION FINISHED")
    print("=" * 70)
    print("Total cases:", len(results))
    print("Passed:", passed)
    print("Failed:", failed)
    print("Errors:", errors)
    print("Transcripts saved in:", TRANSCRIPT_DIR)
    print("=" * 70)



if __name__ == "__main__":
    main()