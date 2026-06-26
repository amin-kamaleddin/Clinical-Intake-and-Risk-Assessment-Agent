from typing import TypedDict, Optional, List


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
    alcohol_use: Optional[str]
    nicotine_use: Optional[str]
    marijuana_use: Optional[str]
    stimulant_use: Optional[str]
    opioid_use: Optional[str]
    benzodiazepine_use: Optional[str]
    hallucinogen_use: Optional[str]
    other_substance_use: Optional[str]


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
        "alcohol_use", "nicotine_use", "marijuana_use", "stimulant_use",
        "opioid_use", "benzodiazepine_use", "hallucinogen_use",
        "other_substance_use",
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


# ── Blank starting state ───────────────────────────────────────────────────────

initial_state: AliceState = {
    "messages":             [],
    "current_section":      None,
    "sections_completed":   [],
    "safety_flag":          False,
    "conversation_started": False,
    "session_id":           "",
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
        "alcohol_use": None,
        "nicotine_use": None,
        "marijuana_use": None,
        "stimulant_use": None,
        "opioid_use": None,
        "benzodiazepine_use": None,
        "hallucinogen_use": None,
        "other_substance_use": None,
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
}
