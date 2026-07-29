"""Shared deterministic-evaluation helpers for the CIRA harness.

Both the live harness (run_evaluation.py) and the offline record checker
(evaluate_records.py) import from here so the two reports compute *identical*
deterministic checks. Previously each file kept its own copy of these helpers,
which had drifted apart.

Medication-format contract (from cira_scenarios.json)
-----------------------------------------------------
Within a medication field, ``;`` separates the *fields of one entry*
(name; dose; start; side effect) and ``. `` separates *distinct entries*::

    "Citalopram; 20 mg; started 2025; dry mouth. Multivitamin; one daily; ..."

So entries are split on sentence boundaries, and the drug *name* is the text
before the first ``;`` of an entry. The name is the stable coverage signal;
matching every field verbatim is brittle and is not done here.
"""

from __future__ import annotations

import re


# --------------------------------------------------------------------------- #
# Text / id primitives
# --------------------------------------------------------------------------- #
def normalize_text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def short_case_id(scenario_case_id: str) -> str:
    """Convert scenario IDs such as '04-01' to record IDs '01'."""
    match = re.search(r"(\d{2})$", str(scenario_case_id))
    if not match:
        raise ValueError(f"Invalid scenario case_id: {scenario_case_id!r}")
    return match.group(1)


# --------------------------------------------------------------------------- #
# Medication parsing
# --------------------------------------------------------------------------- #
def split_medication_entries(value) -> list[str]:
    """Split a medication field into distinct entries on sentence boundaries.

    Uses ``. `` (period + whitespace) as the entry separator, so decimal and
    slash doses like "0.5 mg" or "5/325 mg" stay intact.
    """
    if not value:
        return []
    return [entry.strip() for entry in re.split(r"\.\s+", str(value)) if entry.strip()]


def medication_name(entry: str) -> str:
    """Return the drug name: the text before the first field separator."""
    return entry.split(";")[0].strip()


def expected_medication_entry_count(scenario: dict) -> int:
    """Number of distinct medication entries across current + past fields."""
    meds = scenario.get("patient_facts", {}).get("medications", {}) or {}
    return (
        len(split_medication_entries(meds.get("current_medications")))
        + len(split_medication_entries(meds.get("past_medication_details")))
    )


def medication_capture_check(scenario: dict, medications_state: dict | None) -> dict:
    """Check that each expected drug *name* appears in the saved record.

    Coverage is defined at the drug-name level (the stable signal). Field-level
    details (dose, dates, side effects) are left to the LLM judge, which handles
    paraphrase and formatting drift that a substring check cannot.
    """
    expected_meds = scenario.get("patient_facts", {}).get("medications", {}) or {}
    actual_meds = medications_state or {}

    details = {}
    all_passed = True

    for field in ("current_medications", "past_medication_details"):
        entries = split_medication_entries(expected_meds.get(field))
        expected_names = [medication_name(entry) for entry in entries]
        actual_text = normalize_text(actual_meds.get(field))

        missing = [
            name
            for name in expected_names
            if normalize_text(name) not in actual_text
        ]
        passed = not missing
        all_passed = all_passed and passed
        details[field] = {
            "expected_entries": entries,
            "expected_names": expected_names,
            "actual": actual_meds.get(field),
            "missing_names": missing,
            "passed": passed,
        }

    return {"passed": all_passed, "details": details}


# --------------------------------------------------------------------------- #
# Transcript primitives (shared logic; each caller wraps its own return shape)
# --------------------------------------------------------------------------- #
SAFETY_MARKERS = (
    "immediate safety",
    "call 911",
    "call 988",
    "emergency department",
    "emergency room",
)


def consecutive_duplicate_questions(cira_messages: list[str]) -> list[str]:
    return [
        current
        for previous, current in zip(cira_messages, cira_messages[1:])
        if previous and previous == current
    ]


def safety_response_count(cira_messages: list[str]) -> int:
    return sum(
        any(marker in message for marker in SAFETY_MARKERS)
        for message in cira_messages
    )


def asked_for_additional_medications(cira_messages: list[str]) -> bool:
    return any(
        (
            "any other" in message
            or "any others" in message
            or "anything else" in message
            or "additional medication" in message
        )
        and "medication" in message
        for message in cira_messages
    )
