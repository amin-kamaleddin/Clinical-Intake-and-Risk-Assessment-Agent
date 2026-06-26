from langchain_core.tools import tool


@tool
def save_answer(field_name: str, value: str) -> str:
    """
    Call this every time the patient answers a question or corrects a previous answer.
    field_name: the exact field name (e.g. 'name', 'gender', 'age', 'address')
    value: exactly what the patient said
    """
    return "saved"


@tool
def raise_safety_flag() -> str:
    """
    Call this immediately if the patient mentions:
    - Thoughts of suicide or self-harm
    - Thoughts of harming others
    - A current crisis situation
    """
    return "flag_raised"


tools = [save_answer, raise_safety_flag]
