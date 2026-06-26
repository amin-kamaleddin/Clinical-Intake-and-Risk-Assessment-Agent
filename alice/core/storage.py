import json
import os
from datetime import datetime

from core.state import AliceState


def save_record(state: AliceState) -> None:
    """
    Write the full patient record to records/{session_id}.json.

    Called after every field is entered. The session_id is generated once
    per session, so the filename is stable for the whole intake and is
    never renamed. The id is also stored inside the record itself.
    """
    os.makedirs("records", exist_ok=True)

    session_id = state.get("session_id") or "session"
    filename   = f"records/{session_id}.json"

    record = {
        "session_id": session_id,
        "saved_at": datetime.now().isoformat(),
        "general_information": state["general_information"],
        "current_concerns": state["current_concerns"],
        "past_psychiatric_history": state["past_psychiatric_history"],
        "medications": state["medications"],
        "medical_history": state["medical_history"],
        "medication_allergies": state["medication_allergies"],
        "family_psychiatric_history": state["family_psychiatric_history"],
        "substance_use": state["substance_use"],
        "education_employment_legal_history":
            state["education_employment_legal_history"],
        "personal_history": state["personal_history"],
        "safety_flag": state["safety_flag"],
        "phq9": state["phq9"],
        "gad7": state["gad7"],
    }

    with open(filename, "w") as f:
        json.dump(record, f, indent=2, default=str)
