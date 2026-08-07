"""Field enumeration for record fidelity: code decides scope, the LLM only judges.

The old judge received two JSON blobs and returned a float. That gave the model
discretion over *what counted* as well as *whether it matched*, which is the
main reason its record score was hard to reproduce or defend.

Here the work is split:

1. **Code** (this module) walks ``patient_facts`` and the produced record in
   parallel and emits one row per checkable fact. Fields the scenario leaves
   null are not ground truth and are dropped. Repeatable fields are split so
   capturing 1 of 3 medications cannot score the same as capturing 3 of 3.
2. **Code** auto-resolves every row that needs no judgement at all - exact
   string match, boolean match, empty produced value. On these scenarios that
   is typically half the rows, so the payload and the latency drop, and those
   verdicts carry zero model variance.
3. **The LLM** sees only the genuinely ambiguous rows and returns a categorical
   verdict per row. Models are poorly calibrated on continuous scores and
   reliable on categories, so this is the shape that reruns consistently.
4. **Code** turns verdicts back into the number.

Fabrication is detected here too, by walking the other direction: fields the
record filled where the scenario has no ground truth. Since the patient
simulator is prompt-bound never to invent, anything there is unsupported by
construction - the transcript is not needed to establish it. Per the current
configuration these rows are *reported and not scored*, so a system cannot lose
record points twice for one bad field, and the fabrication count stands on its
own as a metric.
"""

from __future__ import annotations

import re

from harness import config


# Verdicts the judge may return, and what each is worth.
# ``fabricated`` is deliberately absent from the credit table: those rows are
# excluded from the denominator and reported separately.
VERDICT_CREDIT = {
    "match": 1.0,
    "partial": 0.5,
    "missing": 0.0,
    "contradicted": 0.0,
}
VERDICTS = tuple(VERDICT_CREDIT) + ("fabricated",)

# PHQ-9 and GAD-7 belong to harness.structured_score and must never reach the
# judge; scoring them twice by two different methods was the old duplication.
EXCLUDED_SECTIONS = {"phq9", "gad7"}

# Record keys that are bookkeeping rather than clinical content.
NON_CLINICAL_KEYS = {
    "case_id", "scenario_case_id", "title", "system", "persona_id",
    "safety_flag", "safety_reasons", "sections_completed", "issues",
    "patient_behaviour", "messages", "session_id", "current_section",
}

# Abbreviations that end in a period and must not be read as an entry break.
_ABBREVIATIONS = ("dr", "mr", "mrs", "ms", "st", "approx", "no", "vs", "etc")

# A scenario field left null means "the patient has nothing to report here" for
# fields the form still requires an answer to - previous_treatments,
# previous_diagnoses and previous_therapies together account for 22 of these
# across the 12 scenarios. A correct system asks, the patient says "none", and
# the system writes "None". That is the RIGHT answer, not an invention.
#
# Counting it as fabrication produced a floor of exactly 1.833 fabricated
# fields per case for every system, which is what the metric was reporting
# before this check existed. Only a concrete POSITIVE assertion with no ground
# truth behind it is a fabrication now.
#
# The pattern deliberately matches whole short strings only: "no previous
# treatments" is a negation, but "No previous diagnoses; patient reports ADHD"
# contains a claim and is not.
_NEGATION_PATTERN = re.compile(
    r"^(?:none|no|n/?a|nil|nothing|never|unknown|not applicable|not reported"
    r"|not discussed|not provided|not identified|denies|denied"
    r"|patient declined|declined)\b[a-z0-9\s,'\-]*$"
)


def is_negation(value) -> bool:
    """True when a value simply reports the absence of information.

    Trailing punctuation is stripped first: CIRA's section prompts instruct it
    to write "None reported." and "No employment history reported." with a full
    stop, and an earlier version of this pattern rejected every one of them
    because the character class had no ``.``. The strings this must recognise
    are the literal ones in prompts/section_prompts.py, so they are pinned in
    tests/test_scoring.py.
    """
    text = normalize(value).rstrip(".!;: ")
    if not text or len(text) > 70:
        return False
    return bool(_NEGATION_PATTERN.match(text))


def normalize(value) -> str:
    return re.sub(r"\s+", " ", str(value if value is not None else "")).strip().lower()


def split_entries(value) -> list[str]:
    """Split a repeatable field into entries.

    The scenario format uses ``;`` between the fields of one entry and ``. ``
    between entries::

        "Citalopram; 20 mg; started 2025. Multivitamin; one daily"

    Splitting on ``. `` alone would also cut "DR. PETER HALE" in half, so
    abbreviations are stitched back. Decimal and slash doses ("0.5 mg",
    "5/325 mg") are already safe because the pattern requires trailing
    whitespace.
    """
    if not value:
        return []

    pieces = [p for p in re.split(r"\.\s+", str(value)) if p.strip()]
    entries: list[str] = []
    for piece in pieces:
        if entries and entries[-1].split()[-1].strip(".").lower() in _ABBREVIATIONS:
            entries[-1] = f"{entries[-1]}. {piece}"
        else:
            entries.append(piece)
    return [e.strip() for e in entries if e.strip()]


def is_multi_entry(value) -> bool:
    """A repeatable field: uses ``;`` field separators AND holds >1 entry."""
    return isinstance(value, str) and ";" in value and len(split_entries(value)) > 1


def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    return not str(value).strip()


def _bool_of(value):
    """Read a truth value from a bool or a bool-ish string; None if neither."""
    if isinstance(value, bool):
        return value
    text = normalize(value)
    if text in {"true", "yes", "y"}:
        return True
    if text in {"false", "no", "n"}:
        return False
    return None


def _row(section, field, expected, produced, entry_index=None) -> dict:
    ref = f"{section}.{field}"
    if entry_index is not None:
        ref = f"{ref}[{entry_index}]"
    return {
        "ref": ref,
        "section": section,
        "field": field,
        "entry_index": entry_index,
        "expected": expected,
        "produced": produced,
    }


def _auto_verdict(expected, produced, entry_index=None) -> str | None:
    """Resolve a row without the LLM, or return None to send it to the judge."""
    if _is_empty(produced):
        return "missing"

    expected_bool = _bool_of(expected)
    if expected_bool is not None and isinstance(expected, bool):
        produced_bool = _bool_of(produced)
        if produced_bool is None:
            return None
        return "match" if produced_bool == expected_bool else "contradicted"

    expected_text = normalize(expected)
    produced_text = normalize(produced)
    if not expected_text:
        return None
    if expected_text == produced_text:
        return "match"
    # For one entry of a repeatable field, the produced value is the whole
    # field, so containment is the right exact test.
    if entry_index is not None and expected_text in produced_text:
        return "match"
    return None


def build_rows(scenario: dict, record: dict) -> dict:
    """Enumerate every checkable fact for one case.

    Returns ``{"auto": [...], "to_judge": [...], "unsupported": [...]}`` where
    auto rows already carry a ``verdict`` and to_judge rows do not.
    """
    facts = scenario.get("patient_facts", {}) or {}
    auto: list[dict] = []
    to_judge: list[dict] = []
    unsupported: list[dict] = []
    confirmed_absent: list[dict] = []

    for section in config.CANONICAL_SECTIONS:
        if section in EXCLUDED_SECTIONS:
            continue

        expected_section = facts.get(section) or {}
        produced_section = record.get(section)
        produced_section = produced_section if isinstance(produced_section, dict) else {}
        if not isinstance(expected_section, dict):
            continue

        for field, expected in expected_section.items():
            produced = produced_section.get(field)

            if _is_empty(expected):
                # No ground truth to score against. Two very different cases:
                #   "None"          -> the system correctly reported absence
                #   "Prozac 20mg"   -> the system invented a clinical fact
                # Only the second is a fabrication. Neither is scored, since
                # there is nothing to compare a correct answer against.
                if _is_empty(produced) or is_negation(produced):
                    confirmed_absent.append({
                        **_row(section, field, expected, produced),
                        "verdict": "confirmed_absent",
                    })
                else:
                    unsupported.append({
                        **_row(section, field, expected, produced),
                        "verdict": "fabricated",
                        "reason": "scenario provides no value for this field",
                    })
                continue

            if is_multi_entry(expected):
                for index, entry in enumerate(split_entries(expected)):
                    row = _row(section, field, entry, produced, entry_index=index)
                    verdict = _auto_verdict(entry, produced, entry_index=index)
                    (auto if verdict else to_judge).append(
                        {**row, "verdict": verdict} if verdict else row
                    )
                continue

            row = _row(section, field, expected, produced)
            verdict = _auto_verdict(expected, produced)
            (auto if verdict else to_judge).append(
                {**row, "verdict": verdict} if verdict else row
            )

        # Fields the record invented that the scenario's section never defines.
        for field, produced in produced_section.items():
            if field in expected_section or field in NON_CLINICAL_KEYS:
                continue
            if _is_empty(produced) or is_negation(produced):
                continue
            unsupported.append({
                **_row(section, field, None, produced),
                "verdict": "fabricated",
                "reason": "field not present in scenario ground truth",
            })

    return {
        "auto": auto,
        "to_judge": to_judge,
        "unsupported": unsupported,
        "confirmed_absent": confirmed_absent,
    }


def score(rows: list[dict], unsupported: list[dict],
          confirmed_absent: list[dict] | None = None) -> dict:
    """Turn verdicts into ``record_score`` plus a per-section breakdown.

    Rows the judge failed to return a verdict for are counted and excluded
    rather than silently defaulted to a pass or a fail - a missing verdict is a
    harness problem, and quietly scoring it either way would corrupt the number.
    """
    scored = [r for r in rows if r.get("verdict") in VERDICT_CREDIT]
    unjudged = [r for r in rows if r.get("verdict") not in VERDICT_CREDIT]

    credit = sum(VERDICT_CREDIT[r["verdict"]] for r in scored)
    counts = {verdict: 0 for verdict in VERDICTS}
    for row in scored:
        counts[row["verdict"]] += 1
    counts["fabricated"] = len(unsupported)

    by_section: dict[str, dict] = {}
    for row in scored:
        entry = by_section.setdefault(
            row["section"], {"fields": 0, "credit": 0.0, "score": 0.0}
        )
        entry["fields"] += 1
        entry["credit"] += VERDICT_CREDIT[row["verdict"]]
    for entry in by_section.values():
        entry["credit"] = round(entry["credit"], 4)
        entry["score"] = round(entry["credit"] / entry["fields"], 4)

    # Rows the model actually had to judge - the ones where systems can differ.
    # The overall score is diluted by ~20 free rows per case (eight substance_use
    # "Never" answers, twelve booleans) that every system gets right, which is
    # why a no-LLM baseline can tie a full agent on the headline number. The
    # contested score is the discriminating subset.
    contested = [r for r in scored if r.get("verdict_source") == "llm"]
    contested_credit = sum(VERDICT_CREDIT[r["verdict"]] for r in contested)

    return {
        "record_score": round(credit / len(scored), 4) if scored else None,
        "record_score_contested": (
            round(contested_credit / len(contested), 4) if contested else None
        ),
        "fields_contested": len(contested),
        "fields_auto_resolved": len(scored) - len(contested),
        "fields_confirmed_absent": len(confirmed_absent or []),
        "fields_scored": len(scored),
        "fields_unjudged": len(unjudged),
        "unjudged_refs": [r["ref"] for r in unjudged],
        "verdict_counts": counts,
        # Reported, never subtracted: fabrication is its own metric.
        "fabricated_fields": len(unsupported),
        "fabricated_refs": [r["ref"] for r in unsupported],
        "by_section": by_section,
    }
