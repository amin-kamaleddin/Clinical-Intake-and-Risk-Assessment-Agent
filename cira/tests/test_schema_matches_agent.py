"""The record panel must name the same fields the agent writes.

    cd cira
    python -m tests.test_schema_matches_agent

Offline, no keys. core/state.py decides what a record contains; ui/schema.py
decides what is shown and labelled. Nothing connects the two, so a field
renamed in one and not the other fails silently and in the worst possible
direction: the patient answers, the agent stores it, and the panel shows an
empty row. That is how eight substance-use answers were collected and none of
them displayed.

It is worse than invisible. ui.schema.normalize_state_schema writes its
defaults into the state, so a name only the panel believes in is added to
every exported record as a null - a field that looks asked-and-unanswered when
it was never a field at all.
"""

from __future__ import annotations

import sys
import types

# core.state imports core.config, which imports dotenv. Stub it so this runs
# with no dependencies and no .env.
if "dotenv" not in sys.modules:
    _dotenv = types.ModuleType("dotenv")
    _dotenv.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = _dotenv

from core import state as agent_state                       # noqa: E402
from ui.schema import (                                      # noqa: E402
    SECTION_DEFAULTS, FIELD_LABELS, SECTION_TITLES, COMPUTED_FIELDS,
)

#: The TypedDict in core.state that backs each section the panel shows.
SECTION_TYPES = {
    "general_information": "GeneralInformation",
    "current_concerns": "CurrentConcerns",
    "past_psychiatric_history": "PastPsychiatricHistory",
    "medications": "Medications",
    "medical_history": "MedicalHistory",
    "medication_allergies": "MedicationAllergies",
    "family_psychiatric_history": "FamilyPsychiatricHistory",
    "substance_use": "SubstanceUse",
    "education_employment_legal_history": "EducationEmploymentLegalHistory",
    "personal_history": "PersonalHistory",
    "phq9": "PHQ9",
    "gad7": "GAD7",
}

PASSED = 0
FAILURES: list[str] = []


def check(label, condition, detail=""):
    global PASSED
    if condition:
        PASSED += 1
        print(f"  ok    {label}")
    else:
        FAILURES.append(label)
        print(f"  FAIL  {label}" + (f"\n          {detail}" if detail else ""))


def agent_fields(type_name):
    """The field names the agent actually writes for one section."""
    section_type = getattr(agent_state, type_name, None)
    if section_type is None:
        return None
    return set(getattr(section_type, "__annotations__", {}))


def main():
    print("\nevery section the panel shows is a section the agent has")
    for section in SECTION_TITLES:
        check(f"{section} is known to core.state", section in SECTION_TYPES)

    print("\nno field is named by the panel that the agent never writes")
    for section, type_name in SECTION_TYPES.items():
        theirs = agent_fields(type_name)
        if theirs is None:
            check(f"{section}: core.state.{type_name} exists", False,
                  f"no TypedDict named {type_name}")
            continue

        ours = set(SECTION_DEFAULTS.get(section, {}))
        invented = ours - theirs
        check(f"{section}: defaults match the agent", not invented,
              f"the panel invents {sorted(invented)}; the agent writes {sorted(theirs - ours)}")

        labelled = set(FIELD_LABELS.get(section, {}))
        unlabelled_invented = labelled - theirs
        check(f"{section}: labels match the agent", not unlabelled_invented,
              f"labelled but never written: {sorted(unlabelled_invented)}")

    print("\nnothing the agent writes is missing from the panel")
    for section, type_name in SECTION_TYPES.items():
        theirs = agent_fields(type_name) or set()
        shown = set(FIELD_LABELS.get(section, {}))
        computed = COMPUTED_FIELDS.get(section, set())
        missing = theirs - shown - computed
        check(f"{section}: every field is shown", not missing,
              f"collected but never displayed: {sorted(missing)}")

    print("\nevery labelled field has a default, and the reverse")
    for section in SECTION_TITLES:
        defaults = set(SECTION_DEFAULTS.get(section, {}))
        labels = set(FIELD_LABELS.get(section, {}))
        check(f"{section}: defaults and labels agree", defaults == labels,
              f"only in defaults {sorted(defaults - labels)}, "
              f"only in labels {sorted(labels - defaults)}")

    print("\n" + "=" * 66)
    if FAILURES:
        print(f"{len(FAILURES)} CHECK(S) FAILED")
        print("=" * 66)
        sys.exit(1)
    print(f"ALL {PASSED} CHECKS PASSED")
    print("=" * 66)


if __name__ == "__main__":
    main()
