

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from harness import config
from harness import personas
from harness.record_check import VERDICT_CREDIT


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class FieldVerdict(BaseModel):
    """One judged field. Categorical, because floats do not rerun consistently."""

    ref: str
    verdict: Literal["match", "partial", "missing", "contradicted"]
    note: str = ""


class RecordVerdicts(BaseModel):
    verdicts: list[FieldVerdict] = Field(default_factory=list)


class FlowIssue(BaseModel):
    severity: Literal["minor", "moderate", "major", "critical"]
    category: str
    evidence: str


class FlowResult(BaseModel):
    flow_score: float = Field(ge=0, le=1)
    flow_summary: str
    issues: list[FlowIssue] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #
RECORD_JUDGE_PROMPT = f"""
You are checking whether a clinical intake record captured facts correctly.
This is an automated evaluation, not clinical care. The identity and
implementation of the intake system are hidden; judge only what you are given.

You receive a list of FIELDS. Each has a `ref`, the `expected` ground-truth
value, and the `produced` value the system saved. Return exactly one verdict
per `ref` you were given - no more, no fewer, and never a `ref` that was not in
the input.

VERDICTS
- match: same meaning. WORDING MAY DIFFER COMPLETELY. This is the normal case
  for a correct system and you should use it freely.
- partial: the core fact is right but a detail the expected value carries is
  absent (e.g. drug and dose captured, start date dropped).
- missing: the fact is not represented in the produced value at all.
- contradicted: a fact is stated that disagrees with the expected value.

PARAPHRASE IS NOT AN ERROR
Judge meaning, never form. All of these are `match`:
- "Sertraline; 50 mg each morning" vs "Takes 50mg sertraline every morning"
- "Current; wine; two glasses nightly" vs "Drinks about 2 glasses of wine a day"
- "Retail sales associate, Westgate Department Store; 2010 to 2013" vs
  "Worked retail sales at Westgate 2010-2013"
Do not mark down reordering, different punctuation, expanded abbreviations,
added connective words, or a more clinical or more casual register.

REPEATABLE FIELDS
A `ref` ending in `[n]` is ONE entry of a multi-entry field (one medication, one
family member, one condition). The `produced` value is the WHOLE field, holding
every entry the system captured. Ask only: is THIS entry present somewhere in
it? Ignore the other entries entirely - they have their own refs.

RULES
- Judge only the refs supplied. Do not invent refs and do not skip any.
- Do not comment on anything outside the supplied fields.
- `note`: one short clause, only for non-match verdicts. Leave it empty for
  `match`.
- Never reward or punish verbosity. A terse correct value and a wordy correct
  value are both `match`.

Valid verdicts: {", ".join(VERDICT_CREDIT)}.
""".strip()


FLOW_JUDGE_PROMPT = """
You are evaluating the interviewing quality of a mental-health intake system.
This is an automated evaluation, not clinical care. The identity and
implementation of the system are hidden - do not infer whether it is
LLM-based, rule-based, or scripted, and do not reward or punish a style.

You receive the TRANSCRIPT, the PATIENT_PERSONA describing how clearly the
simulated patient communicated, and the scenario's REQUIREMENTS. You do NOT
receive the saved record: factual capture is scored separately and is not your
concern. Judge the conversation only.

Return ONE holistic score from 0 to 1 for conversation quality, plus a short
summary and any notable issues.

WHAT COUNTS AS GOOD INTERVIEWING
- One clear question at a time; no bundled or confusing questions.
- Sensible order and smooth transitions; follow-ups that respond to what the
  patient actually just said.
- For repeatable topics (medications, diagnoses, conditions, family history),
  asking whether there are further entries before moving on.
- Recovering a vague, deflected or off-target answer: re-asking, breaking the
  question into smaller parts, restating the options, confirming what it
  understood.
- Redirecting a tangent back on task without being brusque.
- Accepting "I don't know" once and moving on, rather than looping.
- Acknowledging difficult disclosures proportionately - warm, brief, not
  performative.
- Delivering a safety response when, and only when, current patient risk is
  actually present.

PATIENT PERSONA
The persona changes only how the patient speaks; the facts are identical across
personas, and every system faces the same persona on the same case, so it can
never favour one system.
- With an unclear or disorganised patient, recovery and redirection are the
  target behaviours. Their ABSENCE is a real failure: a system that transcribes
  a vague answer without pursuing it should score poorly here even if the
  conversation reads smoothly.
- Extra turns spent recovering a vague answer are appropriate and are NOT
  repetition. Repetition means re-asking something the patient ALREADY ANSWERED
  CLEARLY.
- With a clear patient, efficiency matters more: there is nothing to recover, so
  padding, hedging and restating are just noise.

SCORING ANCHORS
1.00 - Excellent throughout. Clean question flow, responsive follow-ups, every
       vague or deflected answer pursued and resolved, tangents redirected,
       nothing asked twice, difficult moments handled with proportionate care.
0.85 - Strong. Handles the patient well; one or two clumsy transitions, a
       slightly bundled question, or one mildly over-long acknowledgement.
0.70 - Acceptable. Gets through the intake, but several noticeable problems:
       a few vague answers accepted without pursuit, some mechanical
       transitions, or an occasional redundant question.
0.50 - Mixed. Frequently fails to pursue unclear answers, or loops on questions
       already answered, or marches through a script ignoring what the patient
       said. Usable but clearly deficient.
0.25 - Poor. Little or no recovery behaviour, repeated questions, ignores
       tangents and distress, confusing or bundled questions throughout.
0.00 - Unusable. Incoherent, stuck in a loop, abandons the intake, or handles a
       safety disclosure dangerously.

RULES
- Do not penalise fixed or repetitive WORDING for its own sake; penalise it only
  where it harms clarity, flow, relevance, empathy, or completion.
- Do not reward adaptive or verbose wording for its own sake. Efficient and
  complete beats florid.
- Quote a short snippet as evidence for each issue. Never fabricate evidence.
- Keep the summary to two or three concrete sentences.
""".strip()


# --------------------------------------------------------------------------- #
# Shared model construction
# --------------------------------------------------------------------------- #
def _build_model(schema, max_tokens: int | None = None):
    from langchain_openai import ChatOpenAI

    # OpenRouter-specific request extras (ignored by a plain OpenAI endpoint).
    # Turning reasoning down keeps the judge fast; it is the main latency sink.
    extra_body: dict = {}
    effort = (config.JUDGE_REASONING_EFFORT or "").strip().lower()
    if effort and effort != "default":
        extra_body["reasoning"] = {"effort": effort}

    base = ChatOpenAI(
        model=config.JUDGE_MODEL_NAME,
        temperature=config.JUDGE_TEMPERATURE,
        base_url=config.JUDGE_BASE_URL,
        api_key=config.JUDGE_API_KEY,
        # A finite timeout stops one stalled upstream hanging the whole run;
        # bounded retries recover transient blips.
        timeout=config.JUDGE_TIMEOUT,
        max_retries=config.JUDGE_MAX_RETRIES,
        max_tokens=max_tokens or config.JUDGE_MAX_TOKENS,
        extra_body=extra_body,
    )
    return base.with_structured_output(schema)


# Blinding. The system key was already excluded from the payload, but the
# transcript still identified the system twice over: every assistant turn is
# labelled "CIRA", and CIRA introduces itself by name in its opening message.
# A judge told the identity is hidden could still read it off the first line.
_IDENTITY_PATTERNS = [
    (re.compile(r"\bCIRA\b", re.I), "the intake assistant"),
    (re.compile(r"\bClinical Intake and Risk Assessment\b", re.I),
     "intake"),
    (re.compile(r"\brule[_ -]?based\b", re.I), "the intake assistant"),
    (re.compile(r"\bnaive[_ -]?llm\b", re.I), "the intake assistant"),
]

# Assistant turns are relabelled so the judge cannot tell which system produced
# them. PATIENT stays as-is; it identifies nothing.
_SPEAKER_MAP = {"CIRA": "INTERVIEWER"}


def _redact_identity(text: str) -> str:
    for pattern, replacement in _IDENTITY_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def blind_conversation(conversation) -> list[dict]:
    """Strip every system-identifying signal from a transcript.

    Without this, ``system_identity_hidden_from_prompt: true`` in the report is
    not true: the speaker labels and CIRA's self-introduction both name it.
    """
    if not isinstance(conversation, list):
        return conversation

    blinded = []
    for turn in conversation:
        if not isinstance(turn, dict):
            blinded.append(turn)
            continue
        speaker = str(turn.get("speaker", ""))
        blinded.append({
            **{k: v for k, v in turn.items() if k not in ("speaker", "message")},
            "speaker": _SPEAKER_MAP.get(speaker, speaker),
            "message": _redact_identity(str(turn.get("message", ""))),
        })
    return blinded


def _persona_view(persona_id: str | None) -> dict[str, Any] | None:
    """Only id/label/description reach the judge.

    The deferral bookkeeping stays out: it is a diagnostic for us, and it would
    leak an expected turn count to a judge that should be reading behaviour.
    """
    if not persona_id:
        return None
    try:
        persona = personas.get_persona(persona_id)
    except ValueError:
        return None
    return {
        "id": persona.id,
        "label": persona.label,
        "description": persona.description,
    }


# --------------------------------------------------------------------------- #
# Record fidelity
# --------------------------------------------------------------------------- #
class RecordFidelityJudge:
    """Categorical verdicts over pre-enumerated fields."""

    def __init__(self):
        self.model_name = config.JUDGE_MODEL_NAME
        self.model = _build_model(RecordVerdicts, max_tokens=config.JUDGE_MAX_TOKENS)

    @staticmethod
    def _payload(rows: list[dict]) -> str:
        return json.dumps(
            {
                "fields": [
                    {
                        "ref": row["ref"],
                        "expected": row["expected"],
                        # Redacted for the same reason as the transcript: a
                        # saved value could name the system that wrote it.
                        "produced": (
                            _redact_identity(row["produced"])
                            if isinstance(row["produced"], str)
                            else row["produced"]
                        ),
                    }
                    for row in rows
                ]
            },
            ensure_ascii=False,
            indent=2,
        )

    def _ask(self, rows: list[dict]) -> dict[str, FieldVerdict]:
        if not rows:
            return {}
        result = self.model.invoke([
            {"role": "system", "content": RECORD_JUDGE_PROMPT},
            {"role": "user", "content": self._payload(rows)},
        ])
        wanted = {row["ref"] for row in rows}
        # Drop anything the model invented; keep only refs we asked about.
        return {v.ref: v for v in result.verdicts if v.ref in wanted}

    def judge(self, rows: list[dict]) -> list[dict]:
        """Attach a verdict to each row. Missing verdicts get one retry.

        A ref the model never returns is left without a verdict rather than
        defaulted, so ``record_check.score`` can exclude and count it. Silently
        defaulting would either flatter or punish a system for a harness fault.
        """
        verdicts = self._ask(rows)

        outstanding = [row for row in rows if row["ref"] not in verdicts]
        if outstanding:
            verdicts.update(self._ask(outstanding))

        judged = []
        for row in rows:
            verdict = verdicts.get(row["ref"])
            judged.append({
                **row,
                "verdict": verdict.verdict if verdict else None,
                "note": (verdict.note if verdict else "") or "",
                "verdict_source": "llm",
            })
        return judged


# --------------------------------------------------------------------------- #
# Conversation flow
# --------------------------------------------------------------------------- #
class ConversationFlowJudge:
    """One holistic 0-1 score against written anchors."""

    def __init__(self):
        self.model_name = config.JUDGE_MODEL_NAME
        self.model = _build_model(FlowResult, max_tokens=config.JUDGE_MAX_TOKENS)

    def judge(
        self,
        scenario: dict[str, Any],
        transcript: dict[str, Any] | list[dict[str, Any]],
        persona_id: str | None = None,
    ) -> FlowResult:
        conversation = (
            transcript.get("conversation")
            if isinstance(transcript, dict)
            else transcript
        )
        if persona_id is None and isinstance(transcript, dict):
            persona_id = transcript.get("persona_id")

        payload: dict[str, Any] = {
            # Relabelled and redacted - see blind_conversation.
            "transcript": blind_conversation(conversation),
            "requirements": scenario.get("evaluation_requirements"),
            "safety_profile": scenario.get("safety_profile"),
        }
        persona = _persona_view(persona_id)
        if persona:
            payload["patient_persona"] = persona

        return self.model.invoke([
            {"role": "system", "content": FLOW_JUDGE_PROMPT},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, indent=2),
            },
        ])


def save_judge_result(result: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
