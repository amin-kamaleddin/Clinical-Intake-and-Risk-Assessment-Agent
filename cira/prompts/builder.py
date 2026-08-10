from datetime import date

from core.state import AliceState, REQUIRED_FIELDS, REPEATABLE_TEXT_FIELDS
from prompts.static_prompt import STATIC_PROMPT
from prompts.section_prompts import SECTION_PROMPTS


# Maps a conditional field -> (controlling field, value that hides it).
CONDITIONAL_FIELDS = {
    "family_doctor_name":                 ("has_family_doctor", False),
    "psychiatrist_name":                  ("has_psychiatrist", False),
    "assessment_details":                 ("previously_assessed", False),
    "hospital_details":                   ("hospital_admission", False),
    "self_harm_details":                  ("self_harm_history", False),
    "current_medications":                ("has_current_medications", False),
    "past_medication_details":            ("has_past_medications", False),
    "medical_conditions":                 ("has_medical_conditions", False),
    "surgical_history":                   ("has_surgical_history", False),
    "medication_allergies":               ("has_medication_allergies", False),
    "family_psychiatric_history_details": ("has_family_psychiatric_history", False),
    "legal_case_details":                 ("active_legal_cases", False),
}


def get_pending_fields(state: AliceState, section: str) -> list:
    """Ordered list of fields still to collect, skipping hidden conditionals.

    A repeatable field is NOT complete just because it holds a value. It stays
    pending until the patient has confirmed there are no further entries, which
    is what keeps the section alive long enough for CIRA to ask. Previously the
    first saved entry emptied the pending list, the driver ended the section,
    and every later entry was lost - the single largest source of record error.
    """
    section_data = state[section]
    confirmed = set(state.get("entries_confirmed") or [])
    pending = []

    for field in REQUIRED_FIELDS[section]:
        has_value = section_data.get(field) is not None

        if has_value:
            if field in REPEATABLE_TEXT_FIELDS and field not in confirmed:
                pending.append(field)
            continue

        dependency = CONDITIONAL_FIELDS.get(field)
        if dependency:
            parent, hidden_value = dependency
            if section_data.get(parent) is hidden_value:
                continue
        pending.append(field)

    return pending


def repeatable_status(state: AliceState, section: str) -> str:
    """Prompt text telling the model which repeatable fields still need a 'no more'.

    Without this the model sees a pending field that already holds a value and
    re-asks it from scratch, which reads as repetition. With it, the model knows
    the correct next move is "is there anything else?" followed by the tool call.
    """
    section_data = state[section]
    confirmed = set(state.get("entries_confirmed") or [])

    lines = []
    for field in REQUIRED_FIELDS[section]:
        if field not in REPEATABLE_TEXT_FIELDS:
            continue
        value = section_data.get(field)
        if value is None or field in confirmed:
            continue
        lines.append(
            f"- {field} already holds: {value}\n"
            f"  Do NOT ask for this field again from scratch. Ask only whether "
            f"there are any FURTHER entries. If the patient gives another entry, "
            f"save the combined value with save_answer. When the patient confirms "
            f"there are no more, call confirm_no_more_entries(\"{field}\")."
        )

    if not lines:
        return ""
    return (
        "\nRepeatable fields awaiting confirmation:\n" + "\n".join(lines) + "\n"
    )


def build_section_prompt(state: AliceState) -> str:
    """Build the dynamic, per-turn portion of the system prompt."""
    today      = date.today().strftime("%B %d, %Y")
    name       = state["general_information"].get("name")
    section    = state["current_section"]
    pending    = get_pending_fields(state, section)
    next_field = pending[0] if pending else None

    if not state["conversation_started"]:
        greeting = "This is the start. Greet the patient and introduce yourself as CIRA."
    else:
        greeting = "You have already introduced yourself. Do not greet again."

    return (
        f"Today's date: {today}\n"
        f"Patient name: {name if name else 'not collected yet'}\n"
        f"{greeting}\n\n"
        f"Next field to collect: {next_field}\n"
        f"All pending fields: {pending}\n"
        f"{repeatable_status(state, section)}\n"
        f"{SECTION_PROMPTS[section]}\n\n"
        "When all fields are collected say: "
        "'All done! Please take a look at the panel on the right — "
        "if anything looks incorrect or if you'd like to add or change anything, just let me know.'"
    )


def build_voice_context(state: AliceState) -> str:
    """Tell the model the preferred language and how the latest message arrived."""
    input_source = state.get("latest_input_source", "typed text")
    speech_mode  = "ON" if state.get("speech_to_text_active", False) else "OFF"
    language     = state.get("preferred_language", "English")
    return (
        f"Preferred conversation language: {language}\n"
        f"Speech-to-text mode: {speech_mode}\n"
        f"Latest input source: {input_source}"
    )


SAFETY_HANDLED_DIRECTIVE = """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SAFETY ALREADY HANDLED - RESUME THE INTAKE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The safety flag is raised and the crisis message has ALREADY been delivered to
this patient. That part of your job is done.

- Do NOT send the crisis message again.
- Do NOT keep issuing safety instructions ("tell the nurse", "stay with staff",
  "show them this message"). Repeating them does not increase safety; it stops
  the intake, and the clinician who receives this record needs the rest of it.
- Your next message MUST be the pending intake question named above.
- You may acknowledge what the patient said in one short sentence first, then
  ask the question. One sentence, not a paragraph.
- Record the safety disclosure in the appropriate history field - for a current
  disclosure of suicidal thoughts, save the description in self_harm_details -
  and then continue.
- If the patient discloses again later, acknowledge briefly and keep going. The
  flag is already raised; nothing further is triggered by repetition.
""".strip()


SAFETY_HISTORY_CLEARED_DIRECTIVE = """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SELF-HARM HISTORY ALREADY ASSESSED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Earlier in this intake the patient disclosed a history of self-harm, you asked a
safety clarification, and they confirmed the concern is HISTORICAL with no
current risk. That assessment is recorded and stands.

- Do NOT raise the safety flag, and do NOT repeat the crisis message, if the
  patient mentions that same history again. Referring back to a past event is
  not a new disclosure. Acknowledge it briefly and continue the intake.
- Do NOT ask the safety clarification about that history a second time.
- This does NOT apply to anything new. If the patient describes CURRENT
  suicidal thoughts, a current intent or plan, current self-harm urges, or says
  they cannot stay safe now, raise the flag immediately as normal. A prior
  historical assessment NEVER suppresses a current disclosure.
""".strip()


def build_system_prompt(state: AliceState) -> str:
    """Combine static prompt + voice context + dynamic section prompt.

    Once the safety message has been delivered, an explicit resume directive is
    appended. Without it the conversation fills with safety text and the model
    keeps generating more of it: on the active-risk scenario CIRA issued seven
    consecutive safety instructions, never returned to the pending question, and
    two sections were abandoned - including self_harm_details, the field the
    disclosure was supposed to populate.
    """
    parts = [
        STATIC_PROMPT,
        build_voice_context(state),
        build_section_prompt(state),
    ]
    if state.get("safety_text_sent"):
        parts.append(SAFETY_HANDLED_DIRECTIVE)
    elif state.get("safety_history_cleared"):
        parts.append(SAFETY_HISTORY_CLEARED_DIRECTIVE)
    return "\n\n".join(parts)
