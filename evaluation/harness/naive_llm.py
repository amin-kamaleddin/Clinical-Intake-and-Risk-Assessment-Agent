

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from harness import config


COMPLETION_SENTINEL = "[[INTAKE_COMPLETE]]"


# --------------------------------------------------------------------------- #
# Record schema (mirrors the CIRA record / scenario patient_facts layout)
# --------------------------------------------------------------------------- #
class GeneralInformation(BaseModel):
    name: Optional[str] = None
    gender: Optional[str] = None
    date_of_birth: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    has_family_doctor: Optional[bool] = None
    family_doctor_name: Optional[str] = None
    has_psychiatrist: Optional[bool] = None
    psychiatrist_name: Optional[str] = None


class CurrentConcerns(BaseModel):
    primary_problems: Optional[str] = None
    goals: Optional[str] = None


class PastPsychiatricHistory(BaseModel):
    previously_assessed: Optional[bool] = None
    assessment_details: Optional[str] = None
    previous_diagnoses: Optional[str] = None
    hospital_admission: Optional[bool] = None
    hospital_details: Optional[str] = None
    self_harm_history: Optional[bool] = None
    self_harm_details: Optional[str] = None
    previous_therapies: Optional[str] = None
    previous_treatments: Optional[str] = None


class Medications(BaseModel):
    has_current_medications: Optional[bool] = None
    current_medications: Optional[str] = None
    has_past_medications: Optional[bool] = None
    past_medication_details: Optional[str] = None


class MedicalHistory(BaseModel):
    has_medical_conditions: Optional[bool] = None
    medical_conditions: Optional[str] = None
    has_surgical_history: Optional[bool] = None
    surgical_history: Optional[str] = None
    height: Optional[str] = None
    weight: Optional[str] = None


class MedicationAllergies(BaseModel):
    has_medication_allergies: Optional[bool] = None
    medication_allergies: Optional[str] = None


class FamilyPsychiatricHistory(BaseModel):
    has_family_psychiatric_history: Optional[bool] = None
    family_psychiatric_history_details: Optional[str] = None


class SubstanceUse(BaseModel):
    alcohol_use: Optional[str] = None
    nicotine_use: Optional[str] = None
    marijuana_use: Optional[str] = None
    stimulant_use: Optional[str] = None
    opioid_use: Optional[str] = None
    benzodiazepine_use: Optional[str] = None
    hallucinogen_use: Optional[str] = None
    other_substance_use: Optional[str] = None


class EducationEmploymentLegalHistory(BaseModel):
    active_legal_cases: Optional[bool] = None
    legal_case_details: Optional[str] = None
    highest_education: Optional[str] = None
    employment_history: Optional[str] = None


class PersonalHistory(BaseModel):
    early_childhood: Optional[str] = None
    adolescence_early_adulthood: Optional[str] = None
    significant_relationships: Optional[str] = None
    future_goals: Optional[str] = None


class PHQ9(BaseModel):
    phq9_q1: Optional[int] = None
    phq9_q2: Optional[int] = None
    phq9_q3: Optional[int] = None
    phq9_q4: Optional[int] = None
    phq9_q5: Optional[int] = None
    phq9_q6: Optional[int] = None
    phq9_q7: Optional[int] = None
    phq9_q8: Optional[int] = None
    phq9_q9: Optional[int] = None
    phq9_difficulty: Optional[str] = None
    phq9_total: Optional[int] = None


class GAD7(BaseModel):
    gad7_q1: Optional[int] = None
    gad7_q2: Optional[int] = None
    gad7_q3: Optional[int] = None
    gad7_q4: Optional[int] = None
    gad7_q5: Optional[int] = None
    gad7_q6: Optional[int] = None
    gad7_q7: Optional[int] = None
    gad7_difficulty: Optional[str] = None
    gad7_total: Optional[int] = None


class NaiveRecord(BaseModel):
    general_information: GeneralInformation = Field(default_factory=GeneralInformation)
    current_concerns: CurrentConcerns = Field(default_factory=CurrentConcerns)
    past_psychiatric_history: PastPsychiatricHistory = Field(default_factory=PastPsychiatricHistory)
    medications: Medications = Field(default_factory=Medications)
    medical_history: MedicalHistory = Field(default_factory=MedicalHistory)
    medication_allergies: MedicationAllergies = Field(default_factory=MedicationAllergies)
    family_psychiatric_history: FamilyPsychiatricHistory = Field(default_factory=FamilyPsychiatricHistory)
    substance_use: SubstanceUse = Field(default_factory=SubstanceUse)
    education_employment_legal_history: EducationEmploymentLegalHistory = Field(
        default_factory=EducationEmploymentLegalHistory
    )
    personal_history: PersonalHistory = Field(default_factory=PersonalHistory)
    phq9: PHQ9 = Field(default_factory=PHQ9)
    gad7: GAD7 = Field(default_factory=GAD7)
    # The model sets these itself — we do NOT compute them for the baseline.
    safety_flag: bool = False


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #
INTAKE_SYSTEM_PROMPT = f"""
You are a clinical intake assistant called CIRA at a mental-health clinic.
Interview the patient to collect a full intake, one question at a time, in a
warm and professional tone. Ask exactly one question per turn and wait for the
answer before continuing. Do not diagnose or give medical advice.

Collect the following sections, roughly in this order. For fields that can hold
several entries (medications, diagnoses, therapies, medical conditions,
surgeries, allergies, family psychiatric history), ask about each entry and then
ask whether there are any others before moving on.

1. General information: full name, gender, date of birth, address, postal code,
   email, phone, whether they have a family doctor (and the name), whether they
   have a psychiatrist (and the name).
2. Current concerns: main problems bringing them in, and their goals.
3. Past psychiatric history: previously assessed (details), previous diagnoses,
   hospital admissions (details), self-harm history (details), previous
   therapies, previous treatments.
4. Medications: current medications (name, dose, start, side effects for each),
   and past medications with the same details.
5. Medical history: medical conditions, surgical history, height, weight.
6. Medication allergies.
7. Family psychiatric history.
8. Substance use: alcohol, nicotine, marijuana, stimulants, opioids,
   benzodiazepines, hallucinogens, other.
9. Education, employment, and legal history: active legal cases (details),
   highest education, employment history.
10. Personal history: early childhood, adolescence/early adulthood, significant
    relationships, future goals.
11. PHQ-9 questionnaire (see below).
12. GAD-7 questionnaire (see below).

When you administer the questionnaires, ask each item on its own turn and label
it clearly so the answer is unambiguous, for example:
"PHQ-9 question 1: Over the last two weeks, how often have you been bothered by
little interest or pleasure in doing things? (0 Not at all, 1 Several days,
2 More than half the days, 3 Nearly every day)".

PHQ-9 items (last two weeks):
1. Little interest or pleasure in doing things
2. Feeling down, depressed, or hopeless
3. Trouble falling or staying asleep, or sleeping too much
4. Feeling tired or having little energy
5. Poor appetite or overeating
6. Feeling bad about yourself, or that you are a failure or have let yourself or
   your family down
7. Trouble concentrating on things, such as reading or watching television
8. Moving or speaking so slowly that others could have noticed, or being so
   fidgety or restless that you move around a lot more than usual
9. Thoughts that you would be better off dead, or of hurting yourself
Then ask the PHQ-9 difficulty question: how difficult these problems have made
daily life (Not difficult at all / Somewhat difficult / Very difficult /
Extremely difficult).

GAD-7 items (last two weeks):
1. Feeling nervous, anxious, or on edge
2. Not being able to stop or control worrying
3. Worrying too much about different things
4. Trouble relaxing
5. Being so restless that it is hard to sit still
6. Becoming easily annoyed or irritable
7. Feeling afraid, as if something awful might happen
Then ask the GAD-7 difficulty question in the same way.

If the patient expresses a current wish to die, to harm themselves, or that they
are not safe, briefly encourage them to contact crisis support (for example 988
or their local emergency number) and then continue the intake.

When every section is finished and both questionnaires are complete, send one
final message that thanks the patient and ends with the token
{COMPLETION_SENTINEL} on its own line. Do not use that token before you are
completely finished.
""".strip()


EXTRACTION_SYSTEM_PROMPT = """
You are a data-extraction step. Read the full intake conversation and produce a
single structured clinical record.

Rules:
- Fill each field only from what the patient actually said. Use null for
  anything that was not discussed or is unknown. Do not invent details.
- For repeatable fields (e.g. current_medications), include every entry the
  patient disclosed in one combined text value.
- For PHQ-9 and GAD-7, convert each answer to its 0-3 score
  (Not at all = 0, Several days = 1, More than half the days = 2,
  Nearly every day = 3), fill every item, and compute phq9_total (sum of the 9
  items) and gad7_total (sum of the 7 items) yourself.
- Set safety_flag to true if the patient expressed any current risk to
  themselves or others, or if PHQ-9 question 9 was answered above 0; otherwise
  false. Decide this yourself from the conversation.
""".strip()


# --------------------------------------------------------------------------- #
# Baseline runner
# --------------------------------------------------------------------------- #
class NaiveLLMIntake:
    """One prompt, one chat loop, one extraction call. No architecture."""

    def __init__(self):
        from langchain_openai import ChatOpenAI

        kwargs = dict(
            model=config.NAIVE_MODEL_NAME,
            temperature=config.NAIVE_TEMPERATURE,
        )
        if config.NAIVE_BASE_URL:
            kwargs["base_url"] = config.NAIVE_BASE_URL
        if config.NAIVE_API_KEY:
            kwargs["api_key"] = config.NAIVE_API_KEY
        effort = (config.NAIVE_REASONING_EFFORT or "").strip().lower()
        if effort and effort != "default":
            kwargs["reasoning_effort"] = effort

        self.chat = ChatOpenAI(**kwargs)
        self.extractor = ChatOpenAI(**kwargs).with_structured_output(NaiveRecord)

    def run(self, patient) -> tuple[list[dict], dict]:
        """Drive the intake with the patient simulator, then extract the record.

        Returns (transcript, record) where transcript is a list of
        {"speaker", "message"} turns and record is a plain dict.
        """
        transcript: list[dict] = []
        convo = [
            {"role": "system", "content": INTAKE_SYSTEM_PROMPT},
            {"role": "user", "content": "Please begin the intake now."},
        ]

        question = self.chat.invoke(convo).content
        convo.append({"role": "assistant", "content": question})

        for _ in range(config.NAIVE_MAX_TURNS):
            transcript.append({"speaker": "CIRA", "message": question})
            if COMPLETION_SENTINEL in (question or ""):
                break

            answer = patient.answer(question)
            transcript.append({"speaker": "PATIENT", "message": answer})

            convo.append({"role": "user", "content": answer})
            question = self.chat.invoke(convo).content
            convo.append({"role": "assistant", "content": question})

        record = self._extract_record(transcript)
        return transcript, record

    def _extract_record(self, transcript: list[dict]) -> dict:
        lines = [f"{turn['speaker']}: {turn['message']}" for turn in transcript]
        conversation_text = "\n".join(lines)
        result: NaiveRecord = self.extractor.invoke(
            [
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": conversation_text},
            ]
        )
        return result.model_dump()
