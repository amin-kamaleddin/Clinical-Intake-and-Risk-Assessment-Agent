"""UI-side section schema, labels, and state normalization."""

SECTION_DEFAULTS = {
    "general_information": {
        "name": None, "gender": None, "date_of_birth": None,
        "address": None, "postal_code": None, "email": None,
        "phone": None, "has_family_doctor": None,
        "family_doctor_name": None, "has_psychiatrist": None,
        "psychiatrist_name": None,
    },
    "current_concerns": {
        "primary_problems": None, "goals": None,
    },
    "past_psychiatric_history": {
        "previously_assessed": None, "assessment_details": None,
        "previous_diagnoses": None, "hospital_admission": None,
        "hospital_details": None, "self_harm_history": None,
        "self_harm_details": None, "previous_therapies": None,
        "previous_treatments": None,
    },
    "medications": {
        "has_current_medications": None, "current_medications": None,
        "has_past_medications": None, "past_medication_details": None,
    },
    "medical_history": {
        "has_medical_conditions": None, "medical_conditions": None,
        "has_surgical_history": None, "surgical_history": None,
        "height": None, "weight": None,
    },
    "medication_allergies": {
        "has_medication_allergies": None, "medication_allergies": None,
    },
    "family_psychiatric_history": {
        "has_family_psychiatric_history": None,
        "family_psychiatric_history_details": None,
    },
    "substance_use": {
        "alcohol_use": None, "nicotine_use": None, "marijuana_use": None,
        "stimulant_use": None, "opioid_use": None, "benzodiazepine_use": None,
        "hallucinogen_use": None, "other_substance_use": None,
    },
    "education_employment_legal_history": {
        "active_legal_cases": None, "legal_case_details": None,
        "highest_education": None, "employment_history": None,
    },
    "personal_history": {
        "early_childhood": None, "adolescence_early_adulthood": None,
        "significant_relationships": None, "future_goals": None,
    },
    "phq9": {
        "phq9_q1": None, "phq9_q2": None, "phq9_q3": None, "phq9_q4": None,
        "phq9_q5": None, "phq9_q6": None, "phq9_q7": None, "phq9_q8": None,
        "phq9_q9": None, "phq9_difficulty": None, "phq9_total": None,
    },
    "gad7": {
        "gad7_q1": None, "gad7_q2": None, "gad7_q3": None, "gad7_q4": None,
        "gad7_q5": None, "gad7_q6": None, "gad7_q7": None,
        "gad7_difficulty": None, "gad7_total": None,
    },
}

SECTION_TITLES = {
    "general_information": "General Information",
    "current_concerns": "Current Concerns",
    "past_psychiatric_history": "Past Psychiatric History",
    "medications": "Medications",
    "medical_history": "Medical History",
    "medication_allergies": "Medication Allergies",
    "family_psychiatric_history": "Family Psychiatric History",
    "substance_use": "Substance Use",
    "education_employment_legal_history": "Education, Employment & Legal History",
    "personal_history": "Personal History",
    "phq9": "PHQ-9",
    "gad7": "GAD-7",
}

FIELD_LABELS = {
    "general_information": {
        "name": "Full Name", "gender": "Gender", "date_of_birth": "Date of Birth",
        "address": "Address", "postal_code": "Postal Code", "email": "Email",
        "phone": "Phone", "has_family_doctor": "Has Family Doctor",
        "family_doctor_name": "Family Doctor Name",
        "has_psychiatrist": "Has Psychiatrist",
        "psychiatrist_name": "Psychiatrist Name",
    },
    "current_concerns": {
        "primary_problems": "Primary Problems", "goals": "Appointment Goals",
    },
    "past_psychiatric_history": {
        "previously_assessed": "Previously Assessed",
        "assessment_details": "Assessment Details",
        "previous_diagnoses": "Previous Diagnoses",
        "hospital_admission": "Mental Health Hospital Admission",
        "hospital_details": "Hospital Admission Details",
        "self_harm_history": "History of Intentional Self-Harm",
        "self_harm_details": "History Details",
        "previous_therapies": "Previous Therapies",
        "previous_treatments": "Previous Treatments",
    },
    "medications": {
        "has_current_medications": "Currently Taking Prescribed Medications",
        "current_medications": "Current Medication Details",
        "has_past_medications": "Previously Tried Psychiatric Medications",
        "past_medication_details": "Past Medication Details",
    },
    "medical_history": {
        "has_medical_conditions": "Has Diagnosed Medical Conditions",
        "medical_conditions": "Medical Conditions",
        "has_surgical_history": "Has Surgical History",
        "surgical_history": "Surgical History",
        "height": "Height", "weight": "Weight",
    },
    "medication_allergies": {
        "has_medication_allergies": "Has Medication Allergies",
        "medication_allergies": "Medication Allergy Details",
    },
    "family_psychiatric_history": {
        "has_family_psychiatric_history": "Family Psychiatric History",
        "family_psychiatric_history_details": "Family History Details",
    },
    "substance_use": {
        "alcohol_use": "Alcohol", "nicotine_use": "Nicotine",
        "marijuana_use": "Marijuana / Cannabis", "stimulant_use": "Stimulants",
        "opioid_use": "Opiates / Narcotics", "benzodiazepine_use": "Benzodiazepines",
        "hallucinogen_use": "Hallucinogens", "other_substance_use": "Other Substances",
    },
    "education_employment_legal_history": {
        "active_legal_cases": "Active Legal Cases",
        "legal_case_details": "Legal Case Details",
        "highest_education": "Highest Education",
        "employment_history": "Employment History",
    },
    "personal_history": {
        "early_childhood": "Early Childhood",
        "adolescence_early_adulthood": "Adolescence & Early Adulthood",
        "significant_relationships": "Significant Relationships",
        "future_goals": "Future Goals",
    },
    "phq9": {
        "phq9_q1": "1. Little Interest or Pleasure",
        "phq9_q2": "2. Feeling Down, Depressed, or Hopeless",
        "phq9_q3": "3. Sleep Difficulties",
        "phq9_q4": "4. Tiredness or Low Energy",
        "phq9_q5": "5. Appetite Changes",
        "phq9_q6": "6. Negative Feelings About Yourself",
        "phq9_q7": "7. Difficulty Concentrating",
        "phq9_q8": "8. Slowing Down or Restlessness",
        "phq9_q9": "9. Thoughts of Being Better Off Absent or Self-Harm",
        "phq9_difficulty": "Functional Difficulty",
        "phq9_total": "PHQ-9 Total Score",
    },
    "gad7": {
        "gad7_q1": "1. Feeling Nervous, Anxious, or on Edge",
        "gad7_q2": "2. Unable to Stop or Control Worrying",
        "gad7_q3": "3. Worrying Too Much",
        "gad7_q4": "4. Trouble Relaxing",
        "gad7_q5": "5. Restlessness",
        "gad7_q6": "6. Easily Annoyed or Irritable",
        "gad7_q7": "7. Feeling Afraid Something Awful May Happen",
        "gad7_difficulty": "Functional Difficulty",
        "gad7_total": "GAD-7 Total Score",
    },
}

COMPUTED_FIELDS = {
    "phq9": {"phq9_total"},
    "gad7": {"gad7_total"},
}


def normalize_state_schema(state):
    """Ensure every UI section exists and migrate the old medication schema."""
    if state is None:
        state = {}

    state.setdefault("messages", [])
    state.setdefault("current_section", None)
    state.setdefault("sections_completed", [])
    state.setdefault("safety_flag", False)
    state.setdefault("conversation_started", False)
    state.setdefault("latest_input_source", "typed text")
    state.setdefault("speech_to_text_active", False)
    state.setdefault("preferred_language", "English")

    if not state.get("session_id"):
        import uuid
        state["session_id"] = uuid.uuid4().hex[:8]

    legacy_current = state.get("current_medications", {})
    legacy_past = state.get("past_medications", {})

    if "medications" not in state:
        state["medications"] = {
            "has_current_medications": legacy_current.get("has_current_medications"),
            "current_medications": legacy_current.get("current_medications"),
            "has_past_medications": legacy_past.get("has_past_medications"),
            "past_medication_details": legacy_past.get("past_medication_details"),
        }

    if state.get("current_section") in {"current_medications", "past_medications"}:
        state["current_section"] = "medications"

    for section, defaults in SECTION_DEFAULTS.items():
        section_data = state.setdefault(section, {})
        for field, default_value in defaults.items():
            section_data.setdefault(field, default_value)

    return state
