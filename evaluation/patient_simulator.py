import json 
import os
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI


from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT/'cira'/'.env')

PATIENT_MODEL_NAME = os.getenv(
    "CIRA_PATIENT_MODEL",
    "gpt-5.4-mini",
)

PATIENT_TEMPERATURE = float(
    os.getenv("CIRA_EVAL_TEMPERATURE", "0")
)

class PatientSimulator:
    def __init__(self, scenario:dict):
        self.scenario = scenario

        self.model = ChatOpenAI(
            model = PATIENT_MODEL_NAME,
            temperature = PATIENT_TEMPERATURE 
        )
        self.history = []
        self.system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        patient_facts = json.dumps(
            self.scenario['patient_facts'],
            indent =2,
            ensure_ascii=False
        )
        return f"""

            You are acting as a patient during an automated evaluation of CIRA,
            a clinical intake agent.

            Follow these rules:

            1. Answer only the latest question asked by CIRA.
            2. Use only the patient facts supplied below.
            3. Never invent new information.
            4. Answer naturally, like a real patient.
            5. Do not reveal all patient information at once.
            6. Do not mention that you are an AI, simulator, or test case.
            7. Remain consistent throughout the conversation.
            8. If CIRA asks for clarification, clarify using only the supplied facts.
            9. If a fact is null, say that it does not apply or there is nothing to report.
            10. For PHQ-9 and GAD-7 values, answer using:

            0 = Not at all
            1 = Several days
            2 = More than half the days
            3 = Nearly every day

            Patient description:

            {self.scenario["patient_simulator_instructions"]}

            Patient facts:

            {patient_facts}
            """.strip()
    
    def answer(self, cira_question: str) -> str:
        messages = [SystemMessage(content=self.system_prompt),
        *self.history,
        HumanMessage(content=cira_question),
                ]
        response = self.model.invoke(messages)
        patient_answer = response.content.strip()

        self.history.append(
            AIMessage(content=patient_answer)
        )

        return patient_answer

