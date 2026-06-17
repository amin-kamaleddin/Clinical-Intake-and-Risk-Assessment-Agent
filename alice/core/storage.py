import json
import os
from datetime import datetime

from core.state import AliceState


def save_record(state: AliceState) -> None:
    """
    Write the current patient record to a local JSON file under records/.
    Filename is derived from the patient's name and date of birth so that
    re-saves for the same patient overwrite rather than duplicate.
    """
    os.makedirs("records", exist_ok=True)

    name      = state["general_information"].get("name") or "unknown"
    dob       = state["general_information"].get("date_of_birth") or "unknown"
    name_slug = name.replace(" ", "_").lower()
    dob_slug  = dob.replace("/", "-")
    filename  = f"records/{name_slug}_{dob_slug}.json"

    record = {
        "saved_at":            datetime.now().isoformat(),
        "general_information": state["general_information"],
        "current_concerns":    state["current_concerns"],
        "safety_flag":         state["safety_flag"],
    }

    with open(filename, "w") as f:
        json.dump(record, f, indent=2, default=str)
