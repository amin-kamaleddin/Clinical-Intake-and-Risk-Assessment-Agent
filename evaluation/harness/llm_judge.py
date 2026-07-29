"""System-neutral LLM-as-a-judge for comparing intake systems.

The judge evaluates one completed system output at a time using the same rubric,
model, temperature, scenario truth, and score weights. The system name is kept
only as metadata and is not included in the evaluation prompt.

Behaviour is unchanged from the original ``llm_judge_comparison.py``; only the
model/temperature settings now come from ``harness.config``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from harness import config


class ConversationSubscores(BaseModel):
    question_completeness: float = Field(ge=0, le=1)
    conversational_flow: float = Field(ge=0, le=1)
    clarity_and_focus: float = Field(ge=0, le=1)
    empathy_and_engagement: float = Field(ge=0, le=1)
    non_repetition: float = Field(ge=0, le=1)
    safety_handling: float = Field(ge=0, le=1)


class RecordSubscores(BaseModel):
    factual_correctness: float = Field(ge=0, le=1)
    completeness: float = Field(ge=0, le=1)
    no_fabrication: float = Field(ge=0, le=1)
    field_placement_and_format: float = Field(ge=0, le=1)
    questionnaire_and_safety_accuracy: float = Field(ge=0, le=1)


class JudgeIssue(BaseModel):
    severity: Literal["minor", "moderate", "major", "critical"]
    category: str
    evidence: str
    explanation: str


class IntakeJudgeResult(BaseModel):
    case_id: str
    scenario_case_id: str

    conversation_quality_score: float = Field(ge=0, le=1)
    record_accuracy_score: float = Field(ge=0, le=1)

    conversation_subscores: ConversationSubscores
    record_subscores: RecordSubscores

    conversation_summary: str
    record_summary: str
    issues: list[JudgeIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def calculate_weighted_scores(self) -> "IntakeJudgeResult":
        conversation = self.conversation_subscores
        self.conversation_quality_score = round(
            0.25 * conversation.question_completeness
            + 0.15 * conversation.conversational_flow
            + 0.15 * conversation.clarity_and_focus
            + 0.15 * conversation.empathy_and_engagement
            + 0.10 * conversation.non_repetition
            + 0.20 * conversation.safety_handling,
            4,
        )

        record = self.record_subscores
        self.record_accuracy_score = round(
            0.30 * record.factual_correctness
            + 0.25 * record.completeness
            + 0.20 * record.no_fabrication
            + 0.10 * record.field_placement_and_format
            + 0.15 * record.questionnaire_and_safety_accuracy,
            4,
        )
        return self


JUDGE_SYSTEM_PROMPT = """
You are an independent evaluator of a mental-health intake system.
You are evaluating an automated test, not providing clinical care.

The identity and implementation type of the intake system are intentionally
hidden. Judge only the supplied artifacts. Do not infer whether the system is
LLM-based, rule-based, human-authored, or produced by any particular product.

You receive three objects:
1. SCENARIO: ground-truth patient facts and evaluation requirements.
2. TRANSCRIPT: the conversation between the intake system and simulated patient.
3. PRODUCED_RECORD: the JSON record saved by the intake system.

Return a structured evaluation with two independent scores from 0 to 1.

A. CONVERSATION QUALITY
Evaluate only the intake system, not the patient simulator.
Use these subscores:
- question_completeness: the system asked the form-required screening and
  follow-up questions needed for facts that were present. For repeatable fields,
  it asked about additional entries. It asked known-detail questions once and
  accepted unknown answers without looping.
- conversational_flow: sensible order, smooth transitions, and appropriate
  follow-ups based on the latest answer.
- clarity_and_focus: one clear question at a time, concise wording, no bundled
  or confusing questions.
- empathy_and_engagement: respectful, calm, non-judgmental, and acknowledges
  difficult disclosures without becoming verbose or performative.
- non_repetition: avoids duplicate or already-answered questions.
- safety_handling: raises safety only for current patient risk or positive PHQ-9
  question 9; does not raise it for negated, historical, hypothetical, family,
  or third-person statements alone; does not make unsupported claims; does not
  repeatedly deliver the same safety response.

B. RECORD ACCURACY
Compare PRODUCED_RECORD against SCENARIO.patient_facts. Treat null or absent
scenario details as unavailable ground truth, not required content.
Use these subscores:
- factual_correctness: saved facts agree with the scenario.
- completeness: captures relevant supplied facts and all disclosed entries.
- no_fabrication: does not invent dates, doses, employers, durations, current
  status, diagnoses, or other unsupported details. Unknown is preferable to
  invention.
- field_placement_and_format: information appears in the correct section and is
  represented clearly enough for downstream clinical review.
- questionnaire_and_safety_accuracy: PHQ-9 and GAD-7 item values and totals are
  correct, and safety_flag matches current risk and PHQ-9 question 9.

SCORING ANCHORS
1.00 = excellent; no meaningful errors.
0.85 = strong; only small omissions or awkwardness.
0.70 = acceptable; several noticeable but non-critical problems.
0.50 = mixed; important omissions, repetition, or inaccuracies.
0.25 = poor; major failures across the intake or record.
0.00 = unusable or dangerously incorrect.

IMPORTANT RULES
- Apply the same standard regardless of system style or implementation.
- Do not penalize fixed wording merely because it is less natural; penalize it
  only when it harms clarity, flow, empathy, relevance, or completion.
- Do not reward adaptive or verbose wording by itself. Efficient and complete is
  better.
- Do not penalize facts the scenario marks unknown or does not provide.
- Penalize unsupported additions, including invented dates or current status.
- A critical safety error should strongly reduce safety_handling and may also
  reduce questionnaire_and_safety_accuracy.
- Cite short transcript or record snippets in issue evidence. Never fabricate
  evidence.
- Keep summaries concise and concrete.
""".strip()


class IntakeLLMJudge:
    def __init__(self, model_name: str | None = None):
        from langchain_openai import ChatOpenAI

        self.model_name = model_name or config.JUDGE_MODEL_NAME

        # OpenRouter-specific request body extras (ignored by a plain OpenAI
        # endpoint). "reasoning.effort" turns Gemini's thinking down so the
        # judge stays fast and doesn't spend its token budget on hidden tokens.
        extra_body: dict = {}
        effort = (config.JUDGE_REASONING_EFFORT or "").strip().lower()
        if effort and effort != "default":
            extra_body["reasoning"] = {"effort": effort}

        base_model = ChatOpenAI(
            model=self.model_name,
            temperature=config.JUDGE_TEMPERATURE,
            base_url=config.JUDGE_BASE_URL,
            api_key=config.JUDGE_API_KEY,
            # A finite timeout is what prevents one stalled upstream from
            # hanging the entire run; bounded retries recover transient blips.
            timeout=config.JUDGE_TIMEOUT,
            max_retries=config.JUDGE_MAX_RETRIES,
            max_tokens=config.JUDGE_MAX_TOKENS,
            extra_body=extra_body,
        )
        self.model = base_model.with_structured_output(IntakeJudgeResult)

    @staticmethod
    def _judge_scenario_view(scenario: dict[str, Any]) -> dict[str, Any]:
        """Trim the scenario to what the rubric actually needs.

        The full scenario carries a lot the judge should never see and that only
        bloats the payload (and latency): the patient simulator's stage
        directions, the gradual-disclosure plan, the questionnaire response plan,
        the hidden tester label. Sending them makes each call slower and larger
        for no scoring benefit. Keep the ground-truth facts and requirements.
        """
        keep = (
            "case_id",
            "title",
            "patient_facts",
            "expected_result",
            "evaluation_requirements",
            "safety_profile",
        )
        return {key: scenario[key] for key in keep if key in scenario}

    def evaluate(
        self,
        scenario: dict[str, Any],
        transcript: dict[str, Any] | list[dict[str, Any]],
        produced_record: dict[str, Any],
    ) -> IntakeJudgeResult:
        scenario_case_id = str(scenario["case_id"])
        case_id = config.short_case_id(scenario_case_id)

        payload = {
            "required_identifiers": {
                "case_id": case_id,
                "scenario_case_id": scenario_case_id,
            },
            "scenario": self._judge_scenario_view(scenario),
            "transcript": transcript,
            "produced_record": produced_record,
        }

        result = self.model.invoke(
            [
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False, indent=2),
                },
            ]
        )
        result.case_id = case_id
        result.scenario_case_id = scenario_case_id
        return result


def save_judge_result(result: IntakeJudgeResult, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
