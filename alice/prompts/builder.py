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
    """
    Build the dynamic, per-turn portion of the system prompt.
    Tells the model: today's date, patient name, what to collect next,
    and which section-specific instructions to follow.
    """
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


def build_system_prompt(state: AliceState) -> str:
    """
    Combine the static prompt with the dynamic section prompt.
    This is the full system message passed to the model on every turn.
    """
    return STATIC_PROMPT + "\n\n" + build_section_prompt(state)
