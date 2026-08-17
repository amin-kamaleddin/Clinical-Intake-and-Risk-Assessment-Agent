"""Automated ground-truth consistency audit for the scenario file.

Why this exists
---------------
A scenario can be internally contradictory in a way that silently penalises a
system for being *correct*. The case that prompted this: 04-12 lists prescribed
clonazepam and hydrocodone under ``medications`` while ``substance_use`` records
benzodiazepine and opioid use as ``"Never"``. A system that faithfully reported
the prescribed opioid was scored as contradicting ground truth; a system that
ignored it was rewarded.

That is a data defect, not a system difference, and it moves record-fidelity and
fabrication comparisons. Ground truth has to be checked mechanically before any
result computed from it can be trusted.

The substance fields are named ``nonmedical_*`` so the question they answer is
unambiguous: whether the patient uses the substance OUTSIDE prescribed
treatment. A prescribed benzodiazepine therefore correctly coexists with
``nonmedical_benzodiazepine_use: "Never"``.

Run:

    python -m tools.audit_scenarios          # exits non-zero on any error
    python -m tools.audit_scenarios --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys

from harness import config


# Drug families that appear as prescriptions and also have a substance-use
# field. A prescription alone is fine; the audit only fires when a scenario
# asserts NONMEDICAL use that nothing supports, or the reverse.
DRUG_FAMILIES = {
    "nonmedical_opioid_use": (
        "hydrocodone", "oxycodone", "morphine", "codeine", "tramadol",
        "fentanyl", "hydromorphone", "percocet", "oxycontin", "methadone",
        "buprenorphine", "suboxone",
    ),
    "nonmedical_benzodiazepine_use": (
        "clonazepam", "lorazepam", "diazepam", "alprazolam", "temazepam",
        "ativan", "valium", "xanax", "klonopin",
    ),
    "nonmedical_stimulant_use": (
        "methylphenidate", "amphetamine", "dexamphetamine", "lisdexamfetamine",
        "adderall", "ritalin", "concerta", "vyvanse",
    ),
}

SUBSTANCE_FIELDS = (
    "nonmedical_alcohol_use", "nonmedical_nicotine_use",
    "nonmedical_marijuana_use", "nonmedical_stimulant_use",
    "nonmedical_opioid_use", "nonmedical_benzodiazepine_use",
    "nonmedical_hallucinogen_use", "nonmedical_other_substance_use",
)

LEGACY_SUBSTANCE_FIELDS = tuple(f.replace("nonmedical_", "") for f in SUBSTANCE_FIELDS)


def _text(value) -> str:
    return " ".join(str(value or "").lower().split())


def audit_scenario(scenario: dict) -> list[dict]:
    """Return every consistency problem found in one scenario."""
    case_id = scenario.get("case_id", "?")
    facts = scenario.get("patient_facts", {}) or {}
    problems: list[dict] = []

    def add(level, kind, detail):
        problems.append({"case_id": case_id, "level": level,
                         "kind": kind, "detail": detail})

    substances = facts.get("substance_use") or {}
    medications = facts.get("medications") or {}
    all_meds = " ".join(
        _text(medications.get(k))
        for k in ("current_medications", "past_medication_details")
    )

    # 1. schema: the renamed fields must be present, the legacy ones absent
    for field in SUBSTANCE_FIELDS:
        if field not in substances:
            add("ERROR", "missing_field", f"substance_use.{field} is absent")
    for legacy in LEGACY_SUBSTANCE_FIELDS:
        if legacy in substances:
            add("ERROR", "legacy_field",
                f"substance_use.{legacy} should be nonmedical_{legacy}")

    # 2. a prescription must not be described as nonmedical use of that family
    for field, drugs in DRUG_FAMILIES.items():
        value = _text(substances.get(field))
        prescribed = [d for d in drugs if d in all_meds]
        if not value:
            continue
        never = value.startswith("never")
        if prescribed and not never:
            # Nonmedical use is asserted AND the same family is prescribed.
            # Legitimate only if the value says so explicitly.
            if not re.search(r"non-?medical|recreation|misuse|not prescribed", value):
                add("WARN", "prescription_vs_nonmedical",
                    f"{field}={substances.get(field)!r} while {prescribed} is "
                    f"prescribed - state explicitly whether this is nonmedical use")

    # 3. PHQ-9 / GAD-7 totals must equal the sum of their items
    for instrument, count, total_key in (("phq9", 9, "phq9_total"),
                                         ("gad7", 7, "gad7_total")):
        section = facts.get(instrument) or {}
        items = []
        for index in range(1, count + 1):
            raw = section.get(f"{instrument}_q{index}")
            if raw is None:
                add("ERROR", "missing_item", f"{instrument}_q{index} is absent")
            else:
                try:
                    value = int(raw)
                except (TypeError, ValueError):
                    add("ERROR", "bad_item", f"{instrument}_q{index}={raw!r} is not 0-3")
                    continue
                if not 0 <= value <= 3:
                    add("ERROR", "bad_item", f"{instrument}_q{index}={value} outside 0-3")
                items.append(value)
        expected = scenario.get("expected_result", {}).get(total_key)
        if len(items) == count and expected is not None and sum(items) != expected:
            add("ERROR", "total_mismatch",
                f"{total_key}={expected} but items sum to {sum(items)}")

    # 4. the safety flag must follow from the safety profile and PHQ-9 item 9
    expected_flag = bool(scenario.get("expected_result", {}).get("safety_flag"))
    profile = scenario.get("safety_profile") or {}
    if "patient_current_risk" in profile:
        if bool(profile["patient_current_risk"]) != expected_flag:
            add("ERROR", "safety_profile_mismatch",
                f"safety_flag={expected_flag} but "
                f"patient_current_risk={profile['patient_current_risk']}")
    q9 = (facts.get("phq9") or {}).get("phq9_q9")
    try:
        if q9 is not None and int(q9) > 0 and not expected_flag:
            add("ERROR", "q9_invariant",
                f"phq9_q9={q9} but expected safety_flag is False")
    except (TypeError, ValueError):
        pass

    # 5. a conditional field must agree with its controlling boolean
    for field, (parent, hidden) in config.CONDITIONAL_FIELDS.items():
        for section_name, section in facts.items():
            if not isinstance(section, dict) or field not in section:
                continue
            if section.get(parent) is hidden and section.get(field) is not None:
                add("ERROR", "conditional_contradiction",
                    f"{section_name}.{field} is set while {parent}={hidden}")
            if section.get(parent) is (not hidden) and section.get(field) is None:
                add("WARN", "conditional_empty",
                    f"{section_name}.{field} is null while {parent}={not hidden}")

    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    scenarios = json.loads(config.SCENARIO_FILE.read_text(encoding="utf-8"))
    problems = [p for s in scenarios for p in audit_scenario(s)]

    if args.json:
        print(json.dumps(problems, indent=2))
    else:
        print("=" * 74)
        print(f"SCENARIO CONSISTENCY AUDIT — {len(scenarios)} scenarios")
        print("=" * 74)
        if not problems:
            print("  no problems found")
        for problem in problems:
            print(f"  {problem['level']:<5} {problem['case_id']:<7} "
                  f"{problem['kind']:<28} {problem['detail']}")
        errors = sum(1 for p in problems if p["level"] == "ERROR")
        warnings = len(problems) - errors
        print("-" * 74)
        print(f"  {errors} error(s), {warnings} warning(s)")
        print("\nThis audit is mechanical. It cannot replace clinician review of")
        print("whether the scenarios are clinically coherent.")

    sys.exit(1 if any(p["level"] == "ERROR" for p in problems) else 0)


if __name__ == "__main__":
    main()
