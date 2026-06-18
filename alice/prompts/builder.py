from datetime import date

from core.state import AliceState, REQUIRED_FIELDS
from prompts.static_prompt import STATIC_PROMPT
from prompts.section_prompts import SECTION_PROMPTS


def get_pending_fields(state: AliceState, section: str) -> list[str]:
    """
    Return the ordered list of fields still to be collected in the given section.
    Conditional fields (doctor/psychiatrist name) are excluded when not applicable.
    """
    section_data = state[section]
    return [
        f for f in REQUIRED_FIELDS[section]
        if section_data.get(f) is None
        and not (f == "family_doctor_name" and section_data.get("has_family_doctor") is False)
        and not (f == "psychiatrist_name"  and section_data.get("has_psychiatrist")  is False)
    ]


def build_section_prompt(state: AliceState) -> str:
    """Build the dynamic, per-turn portion of the system prompt."""
    today      = date.today().strftime("%B %d, %Y")
    name       = state["general_information"].get("name")
    section    = state["current_section"]
    pending    = get_pending_fields(state, section)
    next_field = pending[0] if pending else None

    if not state["conversation_started"]:
        greeting = "This is the start. Greet the patient and introduce yourself as ALICE."
    else:
        greeting = "You have already introduced yourself. Do not greet again."

    return (
        f"Today's date: {today}\n"
        f"Patient name: {name if name else 'not collected yet'}\n"
        f"{greeting}\n\n"
        f"Next field to collect: {next_field}\n"
        f"All pending fields: {pending}\n\n"
        f"{SECTION_PROMPTS[section]}\n\n"
        "When all fields are collected say: "
        "'All done! Please take a look at the panel on the right — "
        "if anything looks incorrect or if you'd like to add or change anything, just let me know.'"
    )


def build_voice_context(state: AliceState) -> str:
    """
    Tell the model how the latest message arrived, so it knows whether to
    apply the speech-to-text spelling rules.
    """
    input_source = state.get("latest_input_source", "typed text")
    speech_mode  = "ON" if state.get("speech_to_text_active", False) else "OFF"
    return (
        f"Speech-to-text mode: {speech_mode}\n"
        f"Latest input source: {input_source}"
    )


def build_system_prompt(state: AliceState) -> str:
    """Combine static prompt + voice context + dynamic section prompt."""
    return (
        STATIC_PROMPT
        + "\n\n"
        + build_voice_context(state)
        + "\n\n"
        + build_section_prompt(state)
    )
