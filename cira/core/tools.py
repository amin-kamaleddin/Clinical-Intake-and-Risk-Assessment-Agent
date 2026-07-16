from langchain_core.tools import tool


@tool
def save_answer(field_name: str, value: str) -> str:
    """
    Save a patient's answer or correction.

    Args:
        field_name: The exact intake field name.
        value: The information provided by the patient.
    """
    return "saved"


@tool
def raise_safety_flag() -> str:
    """
    Raise the patient's safety flag only for a current, affirmed safety concern
    involving the patient.

    Call this tool when at least one of the following is true:
    - The patient currently has suicidal thoughts or wishes to be dead.
    - The patient currently intends or plans to harm themselves.
    - The patient currently intends or plans to harm another person.
    - The patient describes another current crisis that creates an immediate
      safety concern.
    - The patient's PHQ-9 question 9 response has a score greater than 0.

    Do not call this tool only because safety-related words appear.

    Do not call it for:
    - A clear denial, such as "I am not suicidal."
    - Historical thoughts or actions with no current concern.
    - A family member's or another person's suicide, self-harm, or risk.
    - Hypothetical, quoted, or educational discussion.
    - Ambiguous wording before asking a brief clarification question.

    The tool records a flag only. It does not contact a care team, emergency
    service, or any other person.
    """
    return "flag_raised"


tools = [save_answer, raise_safety_flag]
