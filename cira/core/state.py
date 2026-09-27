import re

from typing import Dict, TypedDict, Optional, List


# ── Section names that must all be complete before a record is saved ────────────

REQUIRED_SECTIONS = {
    "general_information",
    "current_concerns",
    "past_psychiatric_history",
    "medications",
    "medical_history",
    "medication_allergies",
    "family_psychiatric_history",
    "substance_use",
    "education_employment_legal_history",
    "personal_history",
    "phq9",
    "gad7",
}


# ── Per-section data schemas ────────────────────────────────────────────────────

class GeneralInformation(TypedDict):
    name: Optional[str]
    gender: Optional[str]
    date_of_birth: Optional[str]
    address: Optional[str]
    postal_code: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    has_family_doctor: Optional[bool]
    family_doctor_name: Optional[str]
    has_psychiatrist: Optional[bool]
    psychiatrist_name: Optional[str]


class CurrentConcerns(TypedDict):
    primary_problems: Optional[str]
    goals: Optional[str]


class PastPsychiatricHistory(TypedDict):
    previously_assessed:  Optional[bool]
    assessment_details:   Optional[str]
    previous_diagnoses:   Optional[str]
    hospital_admission:   Optional[bool]
    hospital_details:     Optional[str]
    self_harm_history:    Optional[bool]
    self_harm_details:    Optional[str]
    previous_therapies:   Optional[str]
    previous_treatments:  Optional[str]


class Medications(TypedDict):
    has_current_medications: Optional[bool]
    current_medications: Optional[str]
    has_past_medications: Optional[bool]
    past_medication_details: Optional[str]


class MedicalHistory(TypedDict):
    has_medical_conditions: Optional[bool]
    medical_conditions: Optional[str]
    has_surgical_history: Optional[bool]
    surgical_history: Optional[str]
    height: Optional[str]
    weight: Optional[str]


class MedicationAllergies(TypedDict):
    has_medication_allergies: Optional[bool]
    medication_allergies: Optional[str]


class FamilyPsychiatricHistory(TypedDict):
    has_family_psychiatric_history: Optional[bool]
    family_psychiatric_history_details: Optional[str]


class SubstanceUse(TypedDict):
    nonmedical_alcohol_use: Optional[str]
    nonmedical_nicotine_use: Optional[str]
    nonmedical_marijuana_use: Optional[str]
    nonmedical_stimulant_use: Optional[str]
    nonmedical_opioid_use: Optional[str]
    nonmedical_benzodiazepine_use: Optional[str]
    nonmedical_hallucinogen_use: Optional[str]
    nonmedical_other_substance_use: Optional[str]


class EducationEmploymentLegalHistory(TypedDict):
    active_legal_cases: Optional[bool]
    legal_case_details: Optional[str]
    highest_education: Optional[str]
    employment_history: Optional[str]


class PersonalHistory(TypedDict):
    early_childhood: Optional[str]
    adolescence_early_adulthood: Optional[str]
    significant_relationships: Optional[str]
    future_goals: Optional[str]


class PHQ9(TypedDict):
    phq9_q1: Optional[int]
    phq9_q2: Optional[int]
    phq9_q3: Optional[int]
    phq9_q4: Optional[int]
    phq9_q5: Optional[int]
    phq9_q6: Optional[int]
    phq9_q7: Optional[int]
    phq9_q8: Optional[int]
    phq9_q9: Optional[int]
    phq9_difficulty: Optional[str]
    phq9_total: Optional[int]


class GAD7(TypedDict):
    gad7_q1: Optional[int]
    gad7_q2: Optional[int]
    gad7_q3: Optional[int]
    gad7_q4: Optional[int]
    gad7_q5: Optional[int]
    gad7_q6: Optional[int]
    gad7_q7: Optional[int]
    gad7_difficulty: Optional[str]
    gad7_total: Optional[int]


# ── Top-level graph state ──────────────────────────────────────────────────────

class AliceState(TypedDict):
    messages: List[dict]
    current_section: Optional[str]
    sections_completed: List[str]
    safety_flag: bool
    conversation_started: bool
    session_id: str
    preferred_language: str
    general_information: GeneralInformation
    current_concerns: CurrentConcerns
    past_psychiatric_history: PastPsychiatricHistory
    medications: Medications
    medical_history: MedicalHistory
    medication_allergies: MedicationAllergies
    family_psychiatric_history: FamilyPsychiatricHistory
    substance_use: SubstanceUse
    education_employment_legal_history: EducationEmploymentLegalHistory
    personal_history: PersonalHistory
    phq9: PHQ9
    gad7: GAD7

    # ── Bookkeeping ────────────────────────────────────────────────────────
    #
    # These MUST be declared here, not only in ``initial_state``. LangGraph
    # builds its state channels from this TypedDict's annotations, so any key
    # that is missing from the class is silently dropped from the state that
    # graph.invoke() returns - it survives inside a single node call and then
    # vanishes.
    #
    # Leaving ``entries_confirmed`` undeclared caused a livelock: the model
    # confirmed a repeatable field, the section was marked complete inside the
    # node, the confirmation was stripped on the way out, the driver saw the
    # field pending again, and the same "anything else?" exchange repeated
    # forever.
    safety_text_sent: bool
    # Set once a self-harm history has been disclosed AND clarified as
    # historical with no current risk. The per-section message reset wipes the
    # conversation, so without this the model re-encounters the same history in
    # a later section with no memory of having already cleared it, and raises
    # the flag a second time. That produced the only safety false positive in
    # the benchmark, on the historical-self-injury distractor case.
    safety_history_cleared: bool
    entries_confirmed: List[str]
    repeatable_followups: Dict[str, int]
    # Consecutive turns the stall prompt has fired on the same pending field.
    # Drives the escalation ladder in graph.nodes._stall_prompt.
    stall_streak: Dict[str, int]
    #: How many times a non-English value has been rejected for a field. Bounded,
    #: so a model that will not comply cannot stall the intake forever.
    english_record_rejections: Dict[str, int]


# ── Required fields per section (controls collection order + completion) ─────────

REQUIRED_FIELDS = {
    "general_information": [
        "name", "gender", "date_of_birth", "address", "postal_code",
        "email", "phone", "has_family_doctor", "family_doctor_name",
        "has_psychiatrist", "psychiatrist_name",
    ],
    "current_concerns": [
        "primary_problems", "goals",
    ],
    "past_psychiatric_history": [
        "previously_assessed", "assessment_details",
        "previous_diagnoses",
        "hospital_admission", "hospital_details",
        "self_harm_history", "self_harm_details",
        "previous_therapies", "previous_treatments",
    ],
    "medications": [
        "has_current_medications", "current_medications",
        "has_past_medications", "past_medication_details",
    ],
    "medical_history": [
        "has_medical_conditions", "medical_conditions",
        "has_surgical_history", "surgical_history",
        "height", "weight",
    ],
    "medication_allergies": [
        "has_medication_allergies", "medication_allergies",
    ],
    "family_psychiatric_history": [
        "has_family_psychiatric_history",
        "family_psychiatric_history_details",
    ],
    "substance_use": [
        "nonmedical_alcohol_use", "nonmedical_nicotine_use", "nonmedical_marijuana_use", "nonmedical_stimulant_use",
        "nonmedical_opioid_use", "nonmedical_benzodiazepine_use", "nonmedical_hallucinogen_use",
        "nonmedical_other_substance_use",
    ],
    "education_employment_legal_history": [
        "active_legal_cases", "legal_case_details",
        "highest_education", "employment_history",
    ],
    "personal_history": [
        "early_childhood", "adolescence_early_adulthood",
        "significant_relationships", "future_goals",
    ],
    "phq9": [
        "phq9_q1", "phq9_q2", "phq9_q3", "phq9_q4", "phq9_q5",
        "phq9_q6", "phq9_q7", "phq9_q8", "phq9_q9",
        "phq9_difficulty",
    ],
    "gad7": [
        "gad7_q1", "gad7_q2", "gad7_q3", "gad7_q4",
        "gad7_q5", "gad7_q6", "gad7_q7",
        "gad7_difficulty",
    ],
}


# ── Repeatable free-text fields ────────────────────────────────────────────────
#
# These hold MORE THAN ONE entry (three family members, four medications, two
# jobs). They used to be treated as complete the moment they held any value,
# which ended the section before CIRA could ask "is there anyone/anything else?"
# - the patient's second and third entries were never elicited at all.
#
# They are now only complete once the model has explicitly confirmed there are
# no further entries (see ``entries_confirmed`` below), so the field ends when
# the PATIENT says it is done rather than when the model stops talking.
#
# Defined here rather than in graph/nodes.py so prompts/builder.py can import it
# without a circular import.

REPEATABLE_TEXT_FIELDS = {
    "current_medications", "past_medication_details",
    "previous_diagnoses", "previous_therapies", "previous_treatments",
    "hospital_details", "medical_conditions", "surgical_history",
    "medication_allergies", "family_psychiatric_history_details",
    "employment_history",
}

# How many CONSECUTIVE UNPRODUCTIVE turns a repeatable field may sit open before
# it is auto-confirmed. A safety valve against a model that never calls
# confirm_no_more_entries.
#
# The counter resets whenever a new entry is actually saved, so turns where the
# interview is making progress do not count toward it. Counting every pending
# turn closed family history after three asks while the patient was still
# saying "ask me one person at a time" - two relatives were lost.
MAX_REPEATABLE_FOLLOWUPS = 5


# ── Blank starting state ───────────────────────────────────────────────────────

initial_state: AliceState = {
    "messages":             [],
    "current_section":      None,
    "sections_completed":   [],
    "safety_flag":          False,
    "conversation_started": False,
    "session_id":           "",
    "preferred_language":   "English",
    "general_information": {
        "name": None, "gender": None, "date_of_birth": None,
        "postal_code": None, "address": None, "email": None,
        "phone": None, "has_family_doctor": None,
        "family_doctor_name": None, "has_psychiatrist": None,
        "psychiatrist_name": None,
    },
    "current_concerns": {
        "primary_problems": None,
        "goals": None,
    },
    "past_psychiatric_history": {
        "previously_assessed":  None,
        "assessment_details":   None,
        "previous_diagnoses":   None,
        "hospital_admission":   None,
        "hospital_details":     None,
        "self_harm_history":    None,
        "self_harm_details":    None,
        "previous_therapies":   None,
        "previous_treatments":  None,
    },
    "medications": {
        "has_current_medications": None,
        "current_medications": None,
        "has_past_medications": None,
        "past_medication_details": None,
    },
    "medical_history": {
        "has_medical_conditions": None,
        "medical_conditions": None,
        "has_surgical_history": None,
        "surgical_history": None,
        "height": None,
        "weight": None,
    },
    "medication_allergies": {
        "has_medication_allergies": None,
        "medication_allergies": None,
    },
    "family_psychiatric_history": {
        "has_family_psychiatric_history": None,
        "family_psychiatric_history_details": None,
    },
    "substance_use": {
        "nonmedical_alcohol_use": None,
        "nonmedical_nicotine_use": None,
        "nonmedical_marijuana_use": None,
        "nonmedical_stimulant_use": None,
        "nonmedical_opioid_use": None,
        "nonmedical_benzodiazepine_use": None,
        "nonmedical_hallucinogen_use": None,
        "nonmedical_other_substance_use": None,
    },
    "education_employment_legal_history": {
        "active_legal_cases": None,
        "legal_case_details": None,
        "highest_education": None,
        "employment_history": None,
    },
    "personal_history": {
        "early_childhood": None,
        "adolescence_early_adulthood": None,
        "significant_relationships": None,
        "future_goals": None,
    },
    "phq9": {
        "phq9_q1": None, "phq9_q2": None, "phq9_q3": None,
        "phq9_q4": None, "phq9_q5": None, "phq9_q6": None,
        "phq9_q7": None, "phq9_q8": None, "phq9_q9": None,
        "phq9_difficulty": None, "phq9_total": None,
    },
    "gad7": {
        "gad7_q1": None, "gad7_q2": None, "gad7_q3": None,
        "gad7_q4": None, "gad7_q5": None, "gad7_q6": None,
        "gad7_q7": None, "gad7_difficulty": None, "gad7_total": None,
    },
    # Set once the safety message has been delivered, so it is sent exactly
    # once. Tracked separately from safety_flag, which is now raised before the
    # reply is built and would otherwise suppress its own message.
    "safety_text_sent": False,
    "safety_history_cleared": False,
    # Repeatable fields the patient has confirmed hold no further entries.
    "entries_confirmed": [],
    # field -> how many times we have already asked "any more?" for it.
    "repeatable_followups": {},
    "stall_streak":         {},
    "english_record_rejections": {},
}


# ── Field -> owning section ────────────────────────────────────────────────────
#
# The model can call save_answer for a field belonging to a section other than
# the one currently being collected - the intended behaviour when a patient
# volunteers something out of order, and something the intake explicitly wants
# to capture rather than discard.
#
# Writes used to go to ``state[current_section][field]`` unconditionally. Since
# the state is a plain dict at runtime, that silently created the key inside the
# WRONG section: the record was corrupted, the real field stayed empty and was
# re-asked, and the stray key looked like a fabricated field to the evaluator.
# Routing by field name fixes all three.

FIELD_TO_SECTION = {
    field: section
    for section, fields in REQUIRED_FIELDS.items()
    for field in fields
}
# Derived fields that are written but never "collected".
FIELD_TO_SECTION["phq9_total"] = "phq9"
FIELD_TO_SECTION["gad7_total"] = "gad7"


# ── Conditional fields ─────────────────────────────────────────────────────
#
# field -> (controlling boolean, value that HIDES the field)
#
# A conditional field is only meaningful when its controlling boolean says the
# thing exists. Writing current_medications while has_current_medications is
# False records a medication the patient does not take: in case 04-05 the
# patient's only antidepressant was one she had STOPPED, and it was filed as
# both current and past. The agent's own text said "stopped taking it", so the
# stop was understood and the field was still wrong.
#
# prompts/builder.py has its own copy for deciding which fields are pending.
# This one is for rejecting writes, which is a different job: pending-field
# logic can be talked around by the model, a rejected tool call cannot.
CONDITIONAL_FIELDS = {
    "family_doctor_name": ("has_family_doctor", False),
    "psychiatrist_name": ("has_psychiatrist", False),
    "assessment_details": ("previously_assessed", False),
    "hospital_details": ("hospital_admission", False),
    "self_harm_details": ("self_harm_history", False),
    "current_medications": ("has_current_medications", False),
    "past_medication_details": ("has_past_medications", False),
    "medical_conditions": ("has_medical_conditions", False),
    "surgical_history": ("has_surgical_history", False),
    "medication_allergies": ("has_medication_allergies", False),
    "family_psychiatric_history_details": ("has_family_psychiatric_history", False),
    "legal_case_details": ("active_legal_cases", False),
}


# ── Gate/detail reconciliation ─────────────────────────────────────────────────
#
# Every conditional field is half of a pair: a yes/no gate and its detail
# (has_past_medications / past_medication_details). Both are written only by
# model tool calls, and until this helper existed nothing reconciled the two.

GATE_OF_DETAIL = {detail: gate for detail, (gate, _) in CONDITIONAL_FIELDS.items()}


_NEGATION_PATTERN = re.compile(
    r"^(?:none|no|n/?a|nil|nothing|never|unknown|not applicable|not reported"
    r"|not discussed|not provided|not identified|denies|denied"
    r"|patient declined|declined)\b[a-z0-9\s,'\-]*$"
)


def reports_absence(value) -> bool:
    """True when a free-text value is really an answer of "no"."""
    text = " ".join(str(value or "").split()).strip().lower().rstrip(".!;: ")
    if not text or len(text) > 70:
        return False
    return bool(_NEGATION_PATTERN.match(text))


def infer_gate_from_detail(section_data: dict, field: str) -> Optional[str]:
    """Fill a conditional field's gate boolean when only the detail was written.

    A patient who answers the gate question with content rather than a bare yes
    - "Have you previously tried any psychiatric medications?" / "Yes,
    olanzapine." - answers two fields in one utterance. The model writes the
    detail and drops the boolean.

    Nothing used to reconcile the pair, and every escape route is closed: a gate
    has no CONDITIONAL_FIELDS parent so it can never be hidden, and it is not a
    REPEATABLE_TEXT_FIELD so _auto_confirm_exhausted_followups skips it. The
    gate stayed None, get_pending_fields returned it forever, and the section
    could never complete - the model has the information and believes it is
    finished, so it never asks again and the intake stalls until the driver's
    stall guard ends the section. Six of fifty evaluation intakes ended exactly
    this way, all six with a correct questionnaire and a PASS status.

    The inference is sound rather than a guess: apply_tool_calls REJECTS a
    detail write while its gate is False, so a detail that exists at all can
    only sit under a gate that is None or True. True is the only value the
    missing boolean can take.

    Two guards keep this from touching a healthy record:
      * it writes only into a gate that is None, so an answer the patient
        actually gave is never overwritten;
      * a detail holding an absence marker ("None reported.") is an answer of
        no stored in the detail field. Reading it as evidence the thing exists
        would invert the record, so it is left alone.

    Returns the gate field name when one was filled, otherwise None.
    """
    gate = GATE_OF_DETAIL.get(field)
    if gate is None:
        return None
    detail_value = section_data.get(field)
    if detail_value is None or section_data.get(gate) is not None:
        return None
    if reports_absence(detail_value):
        return None
    section_data[gate] = True
    return gate


# How many consecutive stall prompts a single empty conditional detail may
# absorb before it is recorded as "Unknown" and the interview moves on.
#
# Measured, not guessed. Across the 50-case evaluation, inside the seven
# sections that actually contain a conditional detail, the deepest run of
# consecutive stall prompts in a healthy intake was 2. The two intakes that
# never completed ran to 5 and 7. Four sits clear of both: double the healthy
# maximum, below the lowest stalled one, and under the driver's stall guard of
# 8 so a section still has turns left to recover on its own.
#
# The deep loops in the corpus - up to 9 - were all in phq9/gad7, and neither
# section contains a conditional field, so this ladder cannot reach them. No
# questionnaire item can ever be resolved to "Unknown" by this path.
MAX_EMPTY_DETAIL_FOLLOWUPS = 4


def is_unanswered_conditional_detail(section_data: dict, field: str) -> bool:
    """True when a detail's own gate says it exists but the detail is empty.

    The mirror image of the orphan gate that infer_gate_from_detail repairs, and
    the harder half: a missing boolean can be deduced from the detail, but no
    rule can invent the detail itself.

    This state pins a section open forever. The field cannot be hidden - its
    gate is True, not False - and it cannot be auto-confirmed, because
    _auto_confirm_exhausted_followups closes repeatable fields that already hold
    a value and this one holds nothing. get_pending_fields therefore returns it
    on every turn while the model, which believes it already captured the
    answer, replies with a closing phrase. Two of fifty evaluation intakes ended
    exactly this way.
    """
    dependency = CONDITIONAL_FIELDS.get(field)
    if dependency is None:
        return False
    gate, hidden_value = dependency
    if section_data.get(field) is not None:
        return False
    gate_value = section_data.get(gate)
    return gate_value is not None and gate_value is not hidden_value
