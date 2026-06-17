from typing import TypedDict, Optional, List


# ── Nested data schemas ────────────────────────────────────────────────────────

class GeneralInformation(TypedDict):
    name:               Optional[str]
    gender:             Optional[str]
    date_of_birth:      Optional[str]
    address:            Optional[str]
    postal_code:        Optional[str]
    email:              Optional[str]
    phone:              Optional[str]
    has_family_doctor:  Optional[bool]
    family_doctor_name: Optional[str]
    has_psychiatrist:   Optional[bool]
    psychiatrist_name:  Optional[str]


class CurrentConcerns(TypedDict):
    primary_problems: Optional[str]
    goals:            Optional[str]


# ── Top-level graph state ──────────────────────────────────────────────────────

class AliceState(TypedDict):
    messages:              List[dict]
    current_section:       Optional[str]
    sections_completed:    List[str]
    safety_flag:           bool
    conversation_started:  bool
    general_information:   GeneralInformation
    current_concerns:      CurrentConcerns


# ── Field registry ─────────────────────────────────────────────────────────────
# Defines which fields must be collected, in order, per section.

REQUIRED_FIELDS: dict[str, list[str]] = {
    "general_information": [
        "name",
        "gender",
        "date_of_birth",
        "address",
        "postal_code",
        "email",
        "phone",
        "has_family_doctor",
        "family_doctor_name",
        "has_psychiatrist",
        "psychiatrist_name",
    ],
    "current_concerns": [
        "primary_problems",
        "goals",
    ],
}


# ── Blank starting state ───────────────────────────────────────────────────────

initial_state: AliceState = {
    "messages":             [],
    "current_section":      None,
    "sections_completed":   [],
    "safety_flag":          False,
    "conversation_started": False,
    "general_information": {
        "name":               None,
        "gender":             None,
        "date_of_birth":      None,
        "address":            None,
        "postal_code":        None,
        "email":              None,
        "phone":              None,
        "has_family_doctor":  None,
        "family_doctor_name": None,
        "has_psychiatrist":   None,
        "psychiatrist_name":  None,
    },
    "current_concerns": {
        "primary_problems": None,
        "goals":            None,
    },
}
