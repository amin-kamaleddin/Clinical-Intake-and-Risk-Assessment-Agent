"""Simulate one patient consistently across a complete intake.

Behaviour is unchanged from the original ``patient_simulator.py``; the only
difference is that model/endpoint settings and .env loading now come from
``harness.config`` instead of being recomputed here, so the module works
regardless of where it sits in the tree.
"""

import json
import re
import sys

from harness import config

# langchain is imported lazily inside the methods that need it, so this module
# (and any stage that imports it) loads even when the LLM dependencies are not
# installed. The dependency is only required to actually simulate a patient.


SCORE_TO_RESPONSE = {
    0: "Not at all",
    1: "Several days",
    2: "More than half the days",
    3: "Nearly every day",
}


class PatientSimulator:
    """Simulate one patient consistently across a complete CIRA intake."""

    def __init__(self, scenario: dict):
        from langchain_openai import ChatOpenAI

        self.scenario = scenario
        self.model = ChatOpenAI(
            model=config.PATIENT_MODEL_NAME,
            temperature=config.PATIENT_TEMPERATURE,
            base_url=config.OPENROUTER_BASE_URL,
            api_key=config.OPENROUTER_API_KEY,
        )
        self.history = []
        self.system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        patient_facts = json.dumps(
            self.scenario["patient_facts"],
            indent=2,
            ensure_ascii=False,
        )
        disclosure_plan = json.dumps(
            self.scenario.get("multi_turn_disclosure_plan", {}),
            indent=2,
            ensure_ascii=False,
        )
        safety_profile = json.dumps(
            self.scenario.get("safety_profile", {}),
            indent=2,
            ensure_ascii=False,
        )

        return f"""
You are acting as a patient during an automated evaluation of CIRA,
a clinical intake agent.

GENERAL RULES
1. Answer only CIRA's latest question.
2. Use only the supplied patient facts and plans.
3. Never invent information.
4. Answer naturally and briefly.
5. Do not reveal the full history at once.
6. Never mention being an AI, simulator, evaluation, hidden label, or test case.
7. Remain consistent throughout the conversation.
8. If a fact is null or unknown, say that you do not know or have nothing to report.
9. Do not calculate or disclose PHQ-9 or GAD-7 totals.

MULTI-ENTRY RULES
1. For medications and other repeatable information, reveal one entry at a time.
2. Give missing details for the current entry when CIRA asks.
3. Reveal the next entry only when CIRA asks whether there are any others.
4. After the final entry, clearly say: "No, those are all."
5. Do not repeat an entry already disclosed.
6. If CIRA explicitly asks for all entries together, you may list all supplied entries.
7. Never invent a dose, frequency, start date, duration, or stopping reason.

QUESTIONNAIRE RULES
Use exactly:
0 = Not at all
1 = Several days
2 = More than half the days
3 = Nearly every day

Patient description:
{self.scenario.get("patient_simulator_instructions", "")}

Safety profile:
{safety_profile}

Gradual disclosure plan:
{disclosure_plan}

Patient facts:
{patient_facts}
""".strip()

    @staticmethod
    def _instrument_regex(instrument: str) -> str:
        """Flexible pattern for an instrument name.

        ``instrument`` arrives as a compact key like "phq9"/"gad7", but CIRA
        writes "PHQ-9", "PHQ 9", or "phq9". Insert an optional separator before
        the trailing digit so all spellings match.
        """
        letters = instrument[:-1]
        digit = instrument[-1]
        return rf"{letters}[\s-]?{digit}"

    @classmethod
    def _question_number(cls, question: str, instrument: str, max_question: int) -> int | None:
        """Extract a questionnaire item number from common CIRA wording."""
        lower = question.lower()
        inst = cls._instrument_regex(instrument)

        patterns = [
            # "PHQ-9 question 3", "phq 9 item 3", "phq9 q3", "phq 9 number 3",
            # "phq-9 #3", "phq-9 3"
            rf"{inst}[\s-]*(?:question|item|number|no\.?|#|q)?\s*([1-{max_question}])\b",
            # "question 3 of 9", "question 3 / 9"
            rf"question\s*([1-{max_question}])\s*(?:of|/)\s*{max_question}\b",
            # bare "q3"
            rf"\bq\s*([1-{max_question}])\b",
            # explicit key "phq9_q3" / "phq-9_q3"
            rf"{inst}_q([1-{max_question}])\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, lower)
            if match:
                return int(match.group(1))

        return None

    def _deterministic_questionnaire_answer(self, question: str) -> str | None:
        """Return the exact expected PHQ-9/GAD-7 response when identifiable."""
        phq_number = self._question_number(question, "phq9", 9)
        if phq_number is not None:
            score = self.scenario["patient_facts"]["phq9"][f"phq9_q{phq_number}"]
            return SCORE_TO_RESPONSE[int(score)]

        gad_number = self._question_number(question, "gad7", 7)
        if gad_number is not None:
            score = self.scenario["patient_facts"]["gad7"][f"gad7_q{gad_number}"]
            return SCORE_TO_RESPONSE[int(score)]

        lower = question.lower()
        if "phq-9" in lower or "phq9" in lower:
            if "difficult" in lower:
                return self.scenario["patient_facts"]["phq9"]["phq9_difficulty"]

        if "gad-7" in lower or "gad7" in lower:
            if "difficult" in lower:
                return self.scenario["patient_facts"]["gad7"]["gad7_difficulty"]

        return None

    @staticmethod
    def _looks_like_questionnaire(question: str) -> bool:
        return bool(re.search(r"phq[\s-]?9|gad[\s-]?7", question.lower()))

    def answer(self, cira_question: str) -> str:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        deterministic_answer = self._deterministic_questionnaire_answer(cira_question)

        # Preserve both sides of the conversation in simulator memory.
        self.history.append(HumanMessage(content=cira_question))

        if deterministic_answer is not None:
            patient_answer = deterministic_answer
        else:
            # A question that references an instrument but produced no
            # deterministic answer means the item number could not be parsed;
            # the LLM may answer off the fixed frequency scale and corrupt the
            # PHQ-9/GAD-7 totals. Surface it rather than failing silently.
            if self._looks_like_questionnaire(cira_question):
                print(
                    "[patient_simulator] WARNING: questionnaire item fell through "
                    f"to the LLM (no deterministic answer): {cira_question!r}",
                    file=sys.stderr,
                )
            messages = [
                SystemMessage(content=self.system_prompt),
                *self.history,
            ]
            response = self.model.invoke(messages)
            patient_answer = response.content.strip()

        self.history.append(AIMessage(content=patient_answer))
        return patient_answer
