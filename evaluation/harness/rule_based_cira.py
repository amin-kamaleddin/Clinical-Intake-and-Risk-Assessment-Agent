

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Any

from harness.config import CANONICAL_SECTIONS


AnswerFunction = Callable[[str], str]

# The section list is defined once in harness.config so the engine and the
# deterministic scorer share a single source of truth.
SECTIONS = CANONICAL_SECTIONS

YES = {"yes", "y", "yeah", "yep", "i do", "i have", "correct", "true"}
NO = {"no", "n", "nope", "i don't", "i do not", "none", "never", "false"}
UNKNOWN_MARKERS = ("don't know", "do not know", "not sure", "can't remember", "cannot remember", "unknown")
DECLINE_MARKERS = ("prefer not", "rather not", "decline", "don't want to answer", "do not want to answer")
NO_MORE_MARKERS = (
    "no, those are all", "those are all", "that's all", "that is all", "no more",
    "nothing else", "none other", "no others", "only one", "just that one",
)

PHQ9_QUESTIONS = [
    "Question 1: Over the last two weeks, how often have you had little interest or pleasure in doing things?",
    "Question 2: Over the last two weeks, how often have you felt down, depressed, or hopeless?",
    "Question 3: Over the last two weeks, how often have you had trouble falling or staying asleep, or slept too much?",
    "Question 4: Over the last two weeks, how often have you felt tired or had little energy?",
    "Question 5: Over the last two weeks, how often have you had poor appetite or overeaten?",
    "Question 6: Over the last two weeks, how often have you felt bad about yourself, or that you are a failure or have let yourself or your family down?",
    "Question 7: Over the last two weeks, how often have you had trouble concentrating on things, such as reading or watching television?",
    "Question 8: Over the last two weeks, how often have you been moving or speaking so slowly that other people could have noticed, or been so restless that you moved around much more than usual?",
    "Question 9: Over the last two weeks, how often have you had thoughts that you would be better off absent or of hurting yourself in some way?",
]

GAD7_QUESTIONS = [
    "Question 1: Over the last two weeks, how often have you felt nervous, anxious, or on edge?",
    "Question 2: Over the last two weeks, how often have you been unable to stop or control worrying?",
    "Question 3: Over the last two weeks, how often have you worried too much about different things?",
    "Question 4: Over the last two weeks, how often have you had trouble relaxing?",
    "Question 5: Over the last two weeks, how often have you been so restless that it was hard to sit still?",
    "Question 6: Over the last two weeks, how often have you become easily annoyed or irritable?",
    "Question 7: Over the last two weeks, how often have you felt afraid as if something awful might happen?",
]

SCALE_SUFFIX = (
    " Please answer: Not at all, Several days, More than half the days, "
    "or Nearly every day."
)
DIFFICULTY_OPTIONS = (
    "Not difficult at all, Somewhat difficult, Very difficult, or Extremely difficult."
)


@dataclass
class RuleBasedResult:
    record: dict
    transcript: list[dict]
    safety_flag: bool
    safety_reasons: list[str]
    completed_sections: list[str]
    issues: list[str]


@dataclass
class RuleBasedCIRA:
    max_retries: int = 1
    record: dict = field(default_factory=dict)
    transcript: list[dict] = field(default_factory=list)
    safety_flag: bool = False
    safety_reasons: list[str] = field(default_factory=list)
    completed_sections: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.record = {section: {} for section in SECTIONS}
        self.record["safety_flag"] = False
        self.record["sections_completed"] = []

    # ---------- basic conversation ----------
    def ask(self, section: str, question: str, answer_fn: AnswerFunction) -> str:
        turn = 1 + sum(1 for x in self.transcript if x.get("section") == section and x.get("speaker") == "CIRA")
        self.transcript.append({"section": section, "turn": turn, "speaker": "CIRA", "message": question})
        answer = str(answer_fn(question)).strip()
        self.transcript.append({"section": section, "turn": turn, "speaker": "PATIENT", "message": answer})
        return answer

    @staticmethod
    def clean(answer: str) -> str:
        return re.sub(r"\s+", " ", answer).strip()

    @staticmethod
    def canonical_yes_no(answer: str) -> str | None:
        text = re.sub(r"[^a-z' ]", " ", answer.lower())
        text = re.sub(r"\s+", " ", text).strip()
        if any(phrase in text for phrase in ("not currently", "never have", "do not", "don't", "no ")) or text in NO:
            return "no"
        if text in YES or text.startswith("yes") or text.startswith("yeah") or text.startswith("i have"):
            return "yes"
        return None

    def ask_yes_no(self, section: str, question: str, answer_fn: AnswerFunction) -> str:
        answer = self.ask(section, question, answer_fn)
        parsed = self.canonical_yes_no(answer)
        if parsed is not None:
            return parsed
        retry = self.ask(section, "Please answer yes or no.", answer_fn)
        parsed = self.canonical_yes_no(retry)
        if parsed is None:
            self.issues.append(f"Could not parse yes/no answer in {section}: {retry!r}")
            return "unknown"
        return parsed

    @staticmethod
    def unknown_or_text(answer: str) -> str:
        lower = answer.lower()
        if any(x in lower for x in DECLINE_MARKERS):
            return "Patient declined to answer."
        if any(x in lower for x in UNKNOWN_MARKERS):
            return "Unknown"
        return RuleBasedCIRA.clean(answer)

    @staticmethod
    def no_more(answer: str) -> bool:
        lower = RuleBasedCIRA.clean(answer).lower()
        return any(marker in lower for marker in NO_MORE_MARKERS) or RuleBasedCIRA.canonical_yes_no(answer) == "no"

    #: Answers that mean the same as a JSON boolean. Storing "yes"/"no" while
    #: CIRA, the naive arm and the scenario ground truth all store true/false
    #: made every boolean field look wrong to the record judge - a schema
    #: mismatch scored as an intake failure.
    _BOOL_WORDS = {"yes": True, "no": False}

    def save(self, section: str, field_name: str, value: Any) -> None:
        if isinstance(value, str) and value.strip().lower() in self._BOOL_WORDS:
            value = self._BOOL_WORDS[value.strip().lower()]
        self.record[section][field_name] = value

    def complete(self, section: str) -> None:
        if section not in self.completed_sections:
            self.completed_sections.append(section)
        self.record["sections_completed"] = list(self.completed_sections)

    def raise_safety(self, reason: str) -> None:
        self.safety_flag = True
        self.record["safety_flag"] = True
        if reason not in self.safety_reasons:
            self.safety_reasons.append(reason)

    # ---------- validators / normalizers ----------
    @staticmethod
    def normalize_name(answer: str) -> str:
        return RuleBasedCIRA.clean(answer).upper()

    @staticmethod
    def normalize_gender(answer: str) -> str:
        value = RuleBasedCIRA.clean(answer)
        return value[:1].upper() + value[1:] if value else value

    @staticmethod
    def normalize_dob(answer: str) -> str | None:
        text = RuleBasedCIRA.clean(answer)
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%B %d %Y", "%B %d, %Y", "%d %B %Y", "%b %d %Y", "%d %b %Y"):
            cleaned = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", text, flags=re.I)
            try:
                return datetime.strptime(cleaned, fmt).strftime("%d/%m/%Y")
            except ValueError:
                continue
        return None

    @staticmethod
    def normalize_postal(answer: str) -> str | None:
        compact = re.sub(r"\s+", "", answer).upper()
        return compact if re.fullmatch(r"[A-Z]\d[A-Z]\d[A-Z]\d", compact) else None

    @staticmethod
    def normalize_email(answer: str) -> str | None:
        text = RuleBasedCIRA.clean(answer).replace(" at ", "@").replace(" dot ", ".")
        return text if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", text) else None

    @staticmethod
    def normalize_phone(answer: str) -> str | None:
        digits = re.sub(r"\D", "", answer)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        return digits if len(digits) == 10 else None

    @staticmethod
    def parse_scale(answer: str) -> int | None:
        text = RuleBasedCIRA.clean(answer).lower()
        mapping = {
            "0": 0, "not at all": 0,
            "1": 1, "several days": 1,
            "2": 2, "more than half the days": 2, "more than half of the days": 2,
            "3": 3, "nearly every day": 3,
        }
        if text in mapping:
            return mapping[text]
        for phrase, score in sorted(mapping.items(), key=lambda x: len(x[0]), reverse=True):
            if phrase and phrase in text:
                return score
        return None

    @staticmethod
    def parse_difficulty(answer: str) -> str | None:
        text = RuleBasedCIRA.clean(answer).lower()
        options = {
            "not difficult at all": "Not difficult at all",
            "somewhat difficult": "Somewhat difficult",
            "very difficult": "Very difficult",
            "extremely difficult": "Extremely difficult",
        }
        for phrase, canonical in options.items():
            if phrase in text:
                return canonical
        return None

    # ---------- sections ----------
    def general_information(self, answer_fn: AnswerFunction) -> None:
        s = "general_information"
        name = self.ask(s, "What is your full legal name as it appears on your legal documents?", answer_fn)
        if len(self.clean(name).split()) == 1:
            confirmed = self.ask_yes_no(s, "Is that your complete legal name?", answer_fn)
            if confirmed == "no":
                name = self.ask(s, "Please provide your complete legal name.", answer_fn)
        self.save(s, "name", self.normalize_name(name))

        self.save(s, "gender", self.normalize_gender(self.ask(s, "How would you like your gender recorded?", answer_fn)))

        dob_raw = self.ask(s, "What is your date of birth? You may use DD/MM/YYYY or a written date.", answer_fn)
        dob = self.normalize_dob(dob_raw)
        if dob is None:
            dob = self.normalize_dob(self.ask(s, "Please repeat your date of birth in DD/MM/YYYY format.", answer_fn))
        self.save(s, "date_of_birth", dob or "Unknown")

        address = self.ask(s, "What is your full home address, including street address, city, and province?", answer_fn)
        self.save(s, "address", self.unknown_or_text(address))

        postal_raw = self.ask(s, "What is your Canadian postal code?", answer_fn)
        postal = self.normalize_postal(postal_raw)
        if postal is None:
            postal = self.normalize_postal(self.ask(s, "Please repeat the postal code using letters and numbers.", answer_fn))
        self.save(s, "postal_code", postal or "Unknown")

        email_raw = self.ask(s, "What is your email address?", answer_fn)
        email = self.normalize_email(email_raw)
        if email is None:
            email = self.normalize_email(self.ask(s, "Please repeat your email address.", answer_fn))
        self.save(s, "email", email or "Unknown")

        phone_raw = self.ask(s, "What is your phone number, including area code?", answer_fn)
        phone = self.normalize_phone(phone_raw)
        if phone is None:
            phone = self.normalize_phone(self.ask(s, "Please repeat your 10-digit phone number.", answer_fn))
        self.save(s, "phone", phone or "Unknown")

        has_fd = self.ask_yes_no(s, "Do you currently have a family doctor?", answer_fn)
        self.save(s, "has_family_doctor", has_fd)
        if has_fd == "yes":
            fd = self.ask(s, "What is your family doctor's full first and last name?", answer_fn)
            self.save(s, "family_doctor_name", self.normalize_name(fd) if self.unknown_or_text(fd) != "Unknown" else "unknown")
        else:
            self.save(s, "family_doctor_name", None)

        has_psy = self.ask_yes_no(s, "Do you currently have a psychiatrist?", answer_fn)
        self.save(s, "has_psychiatrist", has_psy)
        if has_psy == "yes":
            psy = self.ask(s, "What is your psychiatrist's full first and last name?", answer_fn)
            self.save(s, "psychiatrist_name", self.normalize_name(psy) if self.unknown_or_text(psy) != "Unknown" else "unknown")
        else:
            self.save(s, "psychiatrist_name", None)
        self.complete(s)

    def current_concerns(self, answer_fn: AnswerFunction) -> None:
        s = "current_concerns"
        problems = self.ask(s, "What main problems or difficulties have you been experiencing lately?", answer_fn)
        if self.canonical_yes_no(problems) == "no" or self.clean(problems).lower() in {"nothing", "none"}:
            problems = "No primary concerns reported at this time."
        self.save(s, "primary_problems", self.unknown_or_text(problems))
        goals = self.ask(s, "What do you hope to get out of your appointment?", answer_fn)
        if self.canonical_yes_no(goals) == "no" or self.clean(goals).lower() in {"nothing", "none"}:
            goals = "No specific goals identified for this appointment."
        self.save(s, "goals", self.unknown_or_text(goals))
        self.complete(s)

    def past_psychiatric_history(self, answer_fn: AnswerFunction) -> None:
        s = "past_psychiatric_history"
        assessed = self.ask_yes_no(s, "Have you ever been assessed by a mental health professional?", answer_fn)
        self.save(s, "previously_assessed", assessed)
        self.save(s, "assessment_details", self.unknown_or_text(self.ask(s, "When were you assessed, and by whom?", answer_fn)) if assessed == "yes" else None)

        diagnoses = self.ask(s, "Have you ever received a psychiatric diagnosis, such as depression, anxiety, OCD, or bipolar disorder? If yes, please list the diagnoses.", answer_fn)
        self.save(s, "previous_diagnoses", "None reported." if self.canonical_yes_no(diagnoses) == "no" else self.unknown_or_text(diagnoses))

        admitted = self.ask_yes_no(s, "Have you ever been admitted to a hospital for mental health reasons?", answer_fn)
        self.save(s, "hospital_admission", admitted)
        self.save(s, "hospital_details", self.unknown_or_text(self.ask(s, "What year was it, where were you admitted, and how long was the stay?", answer_fn)) if admitted == "yes" else None)

        self_harm = self.ask_yes_no(s, "Have you ever thought about or tried to intentionally hurt yourself?", answer_fn)
        self.save(s, "self_harm_history", self_harm)
        if self_harm == "yes":
            detail = self.ask(s, "Please briefly describe what happened. Is there any current or immediate safety concern?", answer_fn)
            self.save(s, "self_harm_details", self.unknown_or_text(detail))
            lower = detail.lower()
            # Denial is checked FIRST and with wider coverage. The old order
            # let the bare word "immediate" in "no current suicidal thoughts or
            # immediate safety concern" register as a current signal, producing
            # a false alarm on the historical-self-injury scenario.
            denied = any(x in lower for x in (
                "no current", "not current", "no immediate", "not immediate",
                "don't have any current", "do not have any current",
                "not anymore", "no longer", "safe now", "able to stay safe",
                "historical", "in the past", "not having any urge",
                "no urge", "wasn't about wanting to die",
                "not about wanting to die",
            ))
            current_signal = any(x in lower for x in (
                "currently", "right now", "today", "immediate",
                "not safe", "can't stay safe", "cannot stay safe",
            ))
            if current_signal and not denied:
                self.raise_safety("Current safety concern disclosed during self-harm history")
        else:
            self.save(s, "self_harm_details", None)

        therapies = self.ask(s, "Have you previously received CBT, DBT, interpersonal therapy, mindfulness-based therapy, psychodynamic therapy, or another therapy?", answer_fn)
        if self.canonical_yes_no(therapies) == "no":
            self.save(s, "previous_therapies", "None reported.")
        else:
            parts = [self.unknown_or_text(therapies)]
            parts.append(self.unknown_or_text(self.ask(s, "When did you receive that therapy?", answer_fn)))
            parts.append(self.unknown_or_text(self.ask(s, "Approximately how many sessions did you attend?", answer_fn)))
            self.save(s, "previous_therapies", "; ".join(parts))

        treatments = self.ask(s, "Have you ever received rTMS, ECT, deep brain stimulation, ketamine treatment, or another biological treatment?", answer_fn)
        if self.canonical_yes_no(treatments) == "no":
            self.save(s, "previous_treatments", "None reported.")
        else:
            details = [self.unknown_or_text(treatments)]
            for question in ("When was it received?", "Where was it received?", "Approximately how many sessions did you receive?", "How long did the benefit or effect last?"):
                details.append(self.unknown_or_text(self.ask(s, question, answer_fn)))
            self.save(s, "previous_treatments", "; ".join(details))
        self.complete(s)

    def _collect_entries(self, section: str, answer_fn: AnswerFunction, first_question: str,
                         detail_questions: list[str], more_question: str, max_entries: int = 8) -> list[dict]:
        entries: list[dict] = []
        first = self.ask(section, first_question, answer_fn)
        if self.canonical_yes_no(first) == "no" or self.clean(first).lower() in {"none", "never"}:
            return entries
        current = {"name_or_description": self.unknown_or_text(first)}
        for key, question in detail_questions:
            current[key] = self.unknown_or_text(self.ask(section, question, answer_fn))
        entries.append(current)
        while len(entries) < max_entries:
            more = self.ask(section, more_question, answer_fn)
            if self.no_more(more):
                break
            current = {"name_or_description": self.unknown_or_text(more)}
            for key, question in detail_questions:
                current[key] = self.unknown_or_text(self.ask(section, question, answer_fn))
            entries.append(current)
        return entries

    @staticmethod
    def summarize_entries(entries: list[dict], label: str) -> str:
        chunks = []
        for i, entry in enumerate(entries, 1):
            values = [f"{key.replace('_', ' ').title()}: {value}" for key, value in entry.items()]
            chunks.append(f"{label} {i}: " + "; ".join(values))
        return "\n".join(chunks)

    def medications(self, answer_fn: AnswerFunction) -> None:
        s = "medications"
        current = self.ask_yes_no(s, "Are you currently taking any prescribed medications?", answer_fn)
        self.save(s, "has_current_medications", current)
        if current == "yes":
            entries = self._collect_entries(
                s, answer_fn,
                "What is the name of your current medication, or its purpose if you do not know the name?",
                [("dose", "What dose do you take?"), ("start_or_duration", "When did you start it, or approximately how long have you taken it?"), ("side_effects", "What side effects have you experienced, if any?")],
                "Are you taking any other prescribed medications? If yes, please give the medication name.",
            )
            self.save(s, "current_medications", self.summarize_entries(entries, "Medication"))
        else:
            self.save(s, "current_medications", None)

        past = self.ask_yes_no(s, "Have you previously tried any psychiatric medications?", answer_fn)
        self.save(s, "has_past_medications", past)
        if past == "yes":
            entries = self._collect_entries(
                s, answer_fn,
                "What was the name of the past psychiatric medication?",
                [("dose", "What dose did you take?"), ("dates_or_duration", "When did you start and stop it, or approximately how long did you take it?"), ("discontinuation_reason", "Why was it discontinued?")],
                "Were there any other past psychiatric medications? If yes, please give the medication name.",
            )
            self.save(s, "past_medication_details", self.summarize_entries(entries, "Past medication"))
        else:
            self.save(s, "past_medication_details", None)
        self.complete(s)

    def medical_history(self, answer_fn: AnswerFunction) -> None:
        s = "medical_history"
        status = self.ask_yes_no(s, "Have you ever been diagnosed with any medical conditions?", answer_fn)
        self.save(s, "has_medical_conditions", status)
        self.save(s, "medical_conditions", self.unknown_or_text(self.ask(s, "Please list all diagnosed medical conditions.", answer_fn)) if status == "yes" else None)
        surgery = self.ask_yes_no(s, "Have you ever had any surgical procedures?", answer_fn)
        self.save(s, "has_surgical_history", surgery)
        if surgery == "yes":
            typ = self.unknown_or_text(self.ask(s, "What type of surgery did you have?", answer_fn))
            date = self.unknown_or_text(self.ask(s, "Approximately when did you have it?", answer_fn))
            details = self.unknown_or_text(self.ask(s, "Are there any other relevant details you wish to provide about the surgery?", answer_fn))
            self.save(s, "surgical_history", f"Surgery: {typ}; Date: {date}; Details: {details}")
        else:
            self.save(s, "surgical_history", None)
        self.save(s, "height", self.unknown_or_text(self.ask(s, "What is your height? You may answer in centimetres or feet and inches.", answer_fn)))
        self.save(s, "weight", self.unknown_or_text(self.ask(s, "What is your weight? You may answer in kilograms or pounds.", answer_fn)))
        self.complete(s)

    def medication_allergies(self, answer_fn: AnswerFunction) -> None:
        s = "medication_allergies"
        status = self.ask_yes_no(s, "Do you have any known allergies to medications?", answer_fn)
        self.save(s, "has_medication_allergies", status)
        if status == "yes":
            entries = self._collect_entries(
                s, answer_fn, "What medication are you allergic to?",
                [("reaction", "What reaction or symptoms did you experience?"), ("date_or_age", "Approximately when did it happen, or how old were you?")],
                "Do you have any other medication allergies? If yes, please give the medication name.",
            )
            self.save(s, "medication_allergies", self.summarize_entries(entries, "Allergy"))
        else:
            self.save(s, "medication_allergies", None)
        self.complete(s)

    def family_psychiatric_history(self, answer_fn: AnswerFunction) -> None:
        s = "family_psychiatric_history"
        status = self.ask_yes_no(s, "Have any of your family members been diagnosed with a mental health condition?", answer_fn)
        self.save(s, "has_family_psychiatric_history", status)
        if status == "yes":
            entries = self._collect_entries(
                s, answer_fn, "Which family member, and what is their relationship to you?",
                [("diagnosis_or_condition", "What diagnosis or mental health condition did they have?"), ("additional_details", "Are there any additional details you wish to provide about that family member?")],
                "Are there any other family members with a mental health condition? If yes, state their relationship to you.",
            )
            self.save(s, "family_psychiatric_history_details", self.summarize_entries(entries, "Family member"))
        else:
            self.save(s, "family_psychiatric_history_details", None)
        self.complete(s)

    def substance_use(self, answer_fn: AnswerFunction) -> None:
        s = "substance_use"
        categories = [
            ("alcohol_use", "alcohol"), ("nicotine_use", "nicotine products such as cigarettes or vaping"),
            ("marijuana_use", "marijuana or cannabis"), ("stimulant_use", "stimulants such as cocaine, methamphetamine, MDMA, or ecstasy"),
            ("opioid_use", "opiates or narcotics"), ("benzodiazepine_use", "benzodiazepines such as Valium, Ativan, or Xanax"),
            ("hallucinogen_use", "hallucinogens such as LSD, PCP, or psilocybin"), ("other_substance_use", "any other substances not already discussed"),
        ]
        for field_name, label in categories:
            status = self.ask(s, f"For {label}, is your use Never, Previous, or Current?", answer_fn)
            low = self.clean(status).lower()
            if "never" in low or self.canonical_yes_no(status) == "no":
                self.save(s, field_name, "Never")
                continue
            canonical_status = "Current" if "current" in low or "currently" in low else "Previous" if "previous" in low or "past" in low or "used to" in low else "Unknown"
            product = self.unknown_or_text(self.ask(s, f"What {label} substance or product did you use?", answer_fn))
            frequency = self.unknown_or_text(self.ask(s, "What was the approximate quantity or frequency?", answer_fn))
            duration = self.unknown_or_text(self.ask(s, "For approximately how long?", answer_fn))
            self.save(s, field_name, f"Status: {canonical_status}; Substance or product: {product}; Quantity or frequency: {frequency}; Duration: {duration}")
        self.complete(s)

    def education_employment_legal_history(self, answer_fn: AnswerFunction) -> None:
        s = "education_employment_legal_history"
        legal = self.ask_yes_no(s, "Are you currently involved in any active legal cases?", answer_fn)
        self.save(s, "active_legal_cases", legal)
        self.save(s, "legal_case_details", self.unknown_or_text(self.ask(s, "Please briefly describe the active legal case. You may decline to provide details.", answer_fn)) if legal == "yes" else None)
        self.save(s, "highest_education", self.unknown_or_text(self.ask(s, "What is the highest level of education you have completed?", answer_fn)))

        employed = self.ask_yes_no(s, "Do you have any recent employment history to report?", answer_fn)
        if employed == "no":
            self.save(s, "employment_history", "No employment history reported.")
        else:
            entries = self._collect_entries(
                s, answer_fn, "What was the employer or organization for your most recent job?",
                [("job_title", "What was your job title?"), ("dates", "What were the start and end dates, or approximate duration? Say Present if you still work there.")],
                "Are there any other recent jobs? If yes, give the employer or organization.",
            )
            self.save(s, "employment_history", self.summarize_entries(entries, "Job"))
        self.complete(s)

    def personal_history(self, answer_fn: AnswerFunction) -> None:
        s = "personal_history"
        self.save(s, "early_childhood", self.unknown_or_text(self.ask(s, "Please describe your early childhood, including where you were born or grew up and what you were like as a young child.", answer_fn)))
        self.save(s, "adolescence_early_adulthood", self.unknown_or_text(self.ask(s, "Please describe your adolescence and early adulthood, including school, difficulties, jobs, responsibilities, or other important experiences.", answer_fn)))
        relationships = self.ask(s, "Please describe any significant romantic relationships you feel are relevant, including type, approximate duration, and whether each is current or ended.", answer_fn)
        if self.canonical_yes_no(relationships) == "no" or self.clean(relationships).lower() in {"none", "never"}:
            relationships = "No significant romantic relationships reported."
        self.save(s, "significant_relationships", self.unknown_or_text(relationships))
        goals = self.ask(s, "What goals do you have for the future?", answer_fn)
        if self.canonical_yes_no(goals) == "no" or self.clean(goals).lower() in {"none", "nothing"}:
            goals = "No specific future goals identified."
        self.save(s, "future_goals", self.unknown_or_text(goals))
        self.complete(s)

    def questionnaire(self, section: str, questions: list[str], answer_fn: AnswerFunction) -> None:
        for index, question in enumerate(questions, 1):
            answer = self.ask(section, question + SCALE_SUFFIX, answer_fn)
            score = self.parse_scale(answer)
            if score is None:
                score = self.parse_scale(self.ask(section, "Please choose one response option: Not at all, Several days, More than half the days, or Nearly every day.", answer_fn))
            if score is None:
                self.issues.append(f"Could not parse {section} question {index}: {answer!r}")
                score = 0
            self.save(section, f"{section}_q{index}", score)
            if section == "phq9" and index == 9 and score > 0:
                self.raise_safety("PHQ-9 question 9 score greater than zero")

        difficulty = self.ask(section, f"How difficult have these problems made work, home responsibilities, or relationships? {DIFFICULTY_OPTIONS}", answer_fn)
        parsed = self.parse_difficulty(difficulty)
        if parsed is None:
            parsed = self.parse_difficulty(self.ask(section, f"Please choose: {DIFFICULTY_OPTIONS}", answer_fn))
        self.save(section, f"{section}_difficulty", parsed or "Unknown")
        total = sum(int(self.record[section][f"{section}_q{i}"]) for i in range(1, len(questions) + 1))
        self.save(section, f"{section}_total", total)
        self.complete(section)

    def run(self, answer_fn: AnswerFunction) -> RuleBasedResult:
        self.general_information(answer_fn)
        self.current_concerns(answer_fn)
        self.past_psychiatric_history(answer_fn)
        self.medications(answer_fn)
        self.medical_history(answer_fn)
        self.medication_allergies(answer_fn)
        self.family_psychiatric_history(answer_fn)
        self.substance_use(answer_fn)
        self.education_employment_legal_history(answer_fn)
        self.personal_history(answer_fn)
        self.questionnaire("phq9", PHQ9_QUESTIONS, answer_fn)
        self.questionnaire("gad7", GAD7_QUESTIONS, answer_fn)
        return RuleBasedResult(
            record=self.record,
            transcript=self.transcript,
            safety_flag=self.safety_flag,
            safety_reasons=self.safety_reasons,
            completed_sections=self.completed_sections,
            issues=self.issues,
        )
