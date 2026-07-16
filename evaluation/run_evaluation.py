import copy
import json
import re
import sys
import uuid
from pathlib import Path

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
RESULTS_DIR = EVALUATION_DIR / "results"
SCENARIO_FILE = EVALUATION_DIR / "cira_scenarios.json"


def load_scenarios() -> list[dict]:
    with SCENARIO_FILE.open("r", encoding="utf-8") as file:
        scenarios = json.load(file)
    if not isinstance(scenarios, list):
        raise ValueError("cira_scenarios.json must contain a list.")
    return scenarios


def get_message_text(message) -> str:
    if isinstance(message, dict):
        return str(message.get("content", ""))
    return str(message.content)


def short_case_id(scenario_case_id: str) -> str:
    """Convert scenario IDs such as '04-01' to record IDs '01'."""
    match = re.search(r"(\d{2})$", str(scenario_case_id))
    if not match:
        raise ValueError(f"Invalid scenario case_id: {scenario_case_id!r}")
    return match.group(1)


def create_cira_state(scenario_case_id: str) -> dict:
    state = copy.deepcopy(initial_state)
    record_case_id = short_case_id(scenario_case_id)

    state["session_id"] = (
        f"evaluation_{scenario_case_id}_{uuid.uuid4().hex[:8]}"
    )
    # Persist both forms in every saved record.
    state["case_id"] = record_case_id
    state["scenario_case_id"] = scenario_case_id
    state["current_section"] = "general_information"
    state["messages"] = []
    return state


def normalize_text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def split_expected_entries(value) -> list[str]:
    if not value:
        return []
    return [
        part.strip()
        for part in re.split(r"[;|]", str(value))
        if part.strip()
    ]


def medication_capture_check(scenario: dict, cira_state: dict) -> dict:
    """Check that identifiable expected medication entries appear in the saved record."""
    expected_meds = scenario.get("patient_facts", {}).get("medications", {})
    actual_meds = cira_state.get("medications", {}) or {}

    details = {}
    all_passed = True

    field_pairs = [
        ("current_medications", "current_medications"),
        ("past_medication_details", "past_medication_details"),
    ]

    for expected_key, actual_key in field_pairs:
        expected_entries = split_expected_entries(expected_meds.get(expected_key))
        actual_text = normalize_text(actual_meds.get(actual_key))

        # Only test concrete entry names. Generic placeholders remain valid but
        # cannot support strict token-level coverage.
        concrete_entries = [
            entry for entry in expected_entries
            if len(normalize_text(entry)) >= 3
        ]
        missing = [
            entry for entry in concrete_entries
            if normalize_text(entry) not in actual_text
        ]

        passed = not missing
        all_passed = all_passed and passed
        details[actual_key] = {
            "expected_entries": concrete_entries,
            "actual": actual_meds.get(actual_key),
            "missing_entries": missing,
            "passed": passed,
        }

    return {"passed": all_passed, "details": details}


def transcript_checks(transcript: list[dict], scenario: dict) -> dict:
    cira_messages = [
        normalize_text(turn["message"])
        for turn in transcript
        if turn.get("speaker") == "CIRA"
    ]

    duplicate_questions = []
    for previous, current in zip(cira_messages, cira_messages[1:]):
        if previous and previous == current:
            duplicate_questions.append(current)

    safety_markers = (
        "immediate safety",
        "call 911",
        "call 988",
        "emergency department",
        "emergency room",
    )
    safety_response_count = sum(
        any(marker in message for marker in safety_markers)
        for message in cira_messages
    )

    expected_meds = scenario.get("patient_facts", {}).get("medications", {})
    expected_count = (
        len(split_expected_entries(expected_meds.get("current_medications")))
        + len(split_expected_entries(expected_meds.get("past_medication_details")))
    )
    asks_for_more = any(
        (
            "any other" in message
            or "any others" in message
            or "anything else" in message
            or "additional medication" in message
        )
        and "medication" in message
        for message in cira_messages
    )

    # Require this only when the scenario has multiple medication entries.
    needs_medication_followup = expected_count > 1

    return {
        "no_consecutive_duplicate_cira_question": {
            "passed": not duplicate_questions,
            "duplicates": duplicate_questions,
        },
        "safety_response_not_repeated": {
            "passed": safety_response_count <= 1,
            "count": safety_response_count,
        },
        "asked_for_additional_medications": {
            "passed": (not needs_medication_followup) or asks_for_more,
            "required": needs_medication_followup,
            "actual": asks_for_more,
        },
    }


def safety_invariant_check(cira_state: dict) -> dict:
    """Check the deterministic rule: PHQ-9 Q9 > 0 must imply safety_flag=True."""
    raw_q9 = cira_state.get("phq9", {}).get("phq9_q9")
    try:
        q9_score = int(raw_q9) if raw_q9 is not None else None
    except (TypeError, ValueError):
        q9_score = None

    required = q9_score is not None and q9_score > 0
    actual = bool(cira_state.get("safety_flag"))
    return {
        "q9_score": q9_score,
        "required": required,
        "actual": actual,
        "passed": (not required) or actual,
    }


def save_transcript(
    scenario: dict,
    transcript: list[dict],
    cira_state: dict,
) -> Path:
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    clean_case_id = scenario["case_id"].replace("-", "_")
    output_file = TRANSCRIPT_DIR / f"case_{clean_case_id}.json"

    transcript_data = {
        "case_id": short_case_id(scenario["case_id"]),
        "scenario_case_id": scenario["case_id"],
        "title": scenario["title"],
        "conversation": transcript,
        "final_result": {
            "safety_flag": cira_state.get("safety_flag"),
            "phq9_total": cira_state.get("phq9", {}).get("phq9_total"),
            "gad7_total": cira_state.get("gad7", {}).get("gad7_total"),
            "completed_sections": cira_state.get("sections_completed", []),
            "medications": cira_state.get("medications", {}),
        },
    }

    with output_file.open("w", encoding="utf-8") as file:
        json.dump(transcript_data, file, indent=2, ensure_ascii=False)

    return output_file


def create_case_result(
    scenario: dict,
    cira_state: dict,
    transcript: list[dict],
    transcript_file: Path,
    issues: list[str],
) -> dict:
    expected = scenario["expected_result"]

    actual = {
        "safety_flag": cira_state.get("safety_flag"),
        "phq9_total": cira_state.get("phq9", {}).get("phq9_total"),
        "gad7_total": cira_state.get("gad7", {}).get("gad7_total"),
        "completed_sections": cira_state.get("sections_completed", []),
    }

    medication_check = medication_capture_check(scenario, cira_state)
    conversation_checks = transcript_checks(transcript, scenario)
    safety_invariant = safety_invariant_check(cira_state)

    checks = {
        "safety_flag": actual["safety_flag"] == expected["safety_flag"],
        "safety_q9_invariant": safety_invariant["passed"],
        "phq9_total": actual["phq9_total"] == expected["phq9_total"],
        "gad7_total": actual["gad7_total"] == expected["gad7_total"],
        "all_sections_completed": set(SECTION_ORDER) <= set(actual["completed_sections"]),
        "medication_coverage": medication_check["passed"],
        "asked_for_additional_medications": conversation_checks[
            "asked_for_additional_medications"
        ]["passed"],
        "no_consecutive_duplicate_cira_question": conversation_checks[
            "no_consecutive_duplicate_cira_question"
        ]["passed"],
        "safety_response_not_repeated": conversation_checks[
            "safety_response_not_repeated"
        ]["passed"],
    }

    passed = all(checks.values()) and not issues

    return {
        "case_id": short_case_id(scenario["case_id"]),
        "scenario_case_id": scenario["case_id"],
        "title": scenario["title"],
        "expected": expected,
        "actual": actual,
        "checks": checks,
        "medication_check": medication_check,
        "conversation_checks": conversation_checks,
        "safety_invariant": safety_invariant,
        "issues": issues,
        "status": "PASS" if passed else "FAIL",
        "transcript_file": str(transcript_file),
    }


def run_case(scenario: dict) -> dict:
    print()
    print("=" * 70)
    print("Case:", scenario["case_id"])
    print("Title:", scenario["title"])
    print("=" * 70)

    patient = PatientSimulator(scenario)
    transcript = []
    issues = []
    cira_state = create_cira_state(scenario["case_id"])
    safety_reported = False

    for section in SECTION_ORDER:
        print()
        print("-" * 70)
        print("Starting section:", section)
        print("-" * 70)

        cira_state["current_section"] = section
        cira_state["messages"] = []
        cira_state = graph.invoke(cira_state)

        pending_fields = get_pending_fields(cira_state, section)
        if not pending_fields:
            print(section, "was already complete.")
            continue

        cira_question = get_message_text(cira_state["messages"][-1])

        for turn_number in range(1, MAX_TURNS_PER_SECTION + 1):
            if not cira_question.strip():
                issue = (
                    f"CIRA returned an empty question in section '{section}'. "
                    f"Pending fields: {pending_fields}"
                )
                print("ERROR:", issue)
                issues.append(issue)
                break

            print()
            print("CIRA:", cira_question)
            transcript.append({
                "section": section,
                "turn": turn_number,
                "speaker": "CIRA",
                "message": cira_question,
            })

            patient_answer = patient.answer(cira_question)
            print("PATIENT:", patient_answer)
            transcript.append({
                "section": section,
                "turn": turn_number,
                "speaker": "PATIENT",
                "message": patient_answer,
            })

            cira_state["messages"] = list(cira_state["messages"]) + [{
                "role": "user",
                "content": patient_answer,
            }]
            cira_state = graph.invoke(cira_state)

            if cira_state.get("safety_flag") and not safety_reported:
                print()
                print("Safety flag raised. Continuing the intake.")
                safety_reported = True

            pending_fields = get_pending_fields(cira_state, section)
            # print("Pending fields:", pending_fields)

            if not pending_fields:
                print()
                print(section, "completed.")
                break

            cira_question = get_message_text(cira_state["messages"][-1])
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
        transcript=transcript,
        transcript_file=transcript_file,
        issues=issues,
    )

    print()
    print("Case result:", result["status"])
    print("Checks:", result["checks"])
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
            results.append(run_case(scenario))
        except Exception as error:
            print()
            print(f"ERROR while running {scenario['case_id']}: {error}")
            results.append({
                "case_id": short_case_id(scenario["case_id"]),
                "scenario_case_id": scenario["case_id"],
                "title": scenario["title"],
                "status": "ERROR",
                "error": str(error),
            })

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    result_file = RESULTS_DIR / "live_evaluation_report.json"
    with result_file.open("w", encoding="utf-8") as file:
        json.dump(results, file, indent=2, ensure_ascii=False)

    passed = sum(result["status"] == "PASS" for result in results)
    failed = sum(result["status"] == "FAIL" for result in results)
    errors = sum(result["status"] == "ERROR" for result in results)

    print()
    print("=" * 70)
    print("EVALUATION FINISHED")
    print("=" * 70)
    print("Total cases:", len(results))
    print("Passed:", passed)
    print("Failed:", failed)
    print("Errors:", errors)
    print("Transcripts saved in:", TRANSCRIPT_DIR)
    print("Results saved to:", result_file)
    print("=" * 70)


if __name__ == "__main__":
    main()
