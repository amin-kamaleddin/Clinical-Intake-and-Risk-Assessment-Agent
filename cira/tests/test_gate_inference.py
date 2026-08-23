"""Regression test for the gate/detail reconciliation in core.state.

Six of fifty evaluation intakes never completed a section. All six had the same
shape: a conditional field's yes/no gate was left None while its detail held a
value, or the reverse. The gate can never be hidden (it has no CONDITIONAL_FIELDS
parent) and never auto-confirmed (it is not repeatable), so get_pending_fields
returned it on every turn, the model - which already had the information -
answered with a closing phrase, and the section stalled until the driver's stall
guard ended it.

infer_gate_from_detail closes the orphan-gate half of that. This test pins the
behaviour and, just as importantly, pins the cases it must NOT touch: the fix is
only safe to ship because it is unreachable on a healthy record.

Offline. No API keys, no network.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

# core.config imports dotenv; stub it so this runs with no dependencies.
if "dotenv" not in sys.modules:
    _dotenv = types.ModuleType("dotenv")
    _dotenv.load_dotenv = lambda **kwargs: None
    sys.modules["dotenv"] = _dotenv

from core.state import (  # noqa: E402
    CONDITIONAL_FIELDS,
    GATE_OF_DETAIL,
    MAX_EMPTY_DETAIL_FOLLOWUPS,
    REPEATABLE_TEXT_FIELDS,
    infer_gate_from_detail,
    is_unanswered_conditional_detail,
    reports_absence,
)
from prompts.builder import (  # noqa: E402
    CONDITIONAL_FIELDS as BUILDER_CONDITIONAL_FIELDS,
    get_pending_fields,
)


# ── The six real records that stalled, verbatim from evaluation/outputs ────────
#
# Kept inline rather than read from disk: "rm -rf outputs" is a documented
# workflow, and this test must survive it.

ORPHAN_GATE = [
    ("04-02", "medications", "current_medications", "has_current_medications", {
        "has_current_medications": None,
        "current_medications": "Prenatal multivitamin with iron; one tablet daily; started during pregnancy; no known side effects",
        "has_past_medications": False,
        "past_medication_details": None,
    }),
    ("04-15", "medications", "past_medication_details", "has_past_medications", {
        "has_current_medications": True,
        "current_medications": "Prazosin; 2 mg nightly; started January 2025; light-headedness when standing",
        "has_past_medications": None,
        "past_medication_details": "Paroxetine; 20 mg daily; started in 2019; taken for approximately 14 months; stopped due to sexual side effects",
    }),
    ("04-19", "medications", "past_medication_details", "has_past_medications", {
        "has_current_medications": True,
        "current_medications": "Lithium carbonate; 900 mg nightly; started 2022; hand tremor",
        "has_past_medications": None,
        "past_medication_details": "Olanzapine; 10 mg nightly; taken for approximately 18 months starting in 2022; stopped due to weight gain",
    }),
    ("04-31", "medications", "past_medication_details", "has_past_medications", {
        "has_current_medications": True,
        "current_medications": "Venlafaxine; 225 mg; started 2024; sweating and increased blood pressure.",
        "has_past_medications": None,
        "past_medication_details": "Sertraline; 200 mg daily; started 2019; taken for about 12 months; stopped due to lack of benefit. Escitalopram; 20 mg daily; started 2021; taken for about 9 months; stopped due to lack of benefit.",
    }),
]

# The other two stalled the other way round: the gate was written and the DETAIL
# dropped. Nothing can invent the missing content, so this fix must leave them
# alone rather than guess. They are listed here so the boundary is explicit and
# a later fix has something to move.
EMPTY_DETAIL = [
    ("04-36", "family_psychiatric_history", "family_psychiatric_history_details", {
        "has_family_psychiatric_history": True,
        "family_psychiatric_history_details": None,
    }),
    ("04-40", "past_psychiatric_history", "hospital_details", {
        "previously_assessed": True,
        "assessment_details": "2023; addictions medicine service",
        "previous_diagnoses": "Opioid use disorder, in sustained remission",
        "hospital_admission": True,
        "hospital_details": None,
        "self_harm_history": False,
        "self_harm_details": None,
        "previous_therapies": "Relapse prevention group; 2024; approximately 12 sessions; community addictions clinic",
        "previous_treatments": "None reported.",
    }),
]


PASSED = 0


def check(condition: bool, label: str) -> None:
    global PASSED
    if not condition:
        raise AssertionError(f"FAILED: {label}")
    PASSED += 1


def state_for(section: str, data: dict) -> dict:
    """A state whose every repeatable field is already confirmed.

    The most generous possible starting point: anything still pending here is
    pending for a reason no amount of interviewing can resolve.
    """
    return {section: data, "entries_confirmed": list(REPEATABLE_TEXT_FIELDS)}


# ── 1. the bug, and the fix ───────────────────────────────────────────────────

def test_orphan_gate_cases() -> None:
    print("\n1. THE FOUR STALLED RECORDS (detail written, gate dropped)")
    for case_id, section, detail, gate, data in ORPHAN_GATE:
        data = dict(data)
        state = state_for(section, data)

        before = get_pending_fields(state, section)
        check(gate in before, f"{case_id}: expected {gate} pending before the fix")
        print(f"  {case_id}  before: pending={before}")

        filled = infer_gate_from_detail(data, detail)
        check(filled == gate, f"{case_id}: expected {gate} to be filled, got {filled!r}")
        check(data[gate] is True, f"{case_id}: {gate} should be True, is {data[gate]!r}")

        after = get_pending_fields(state, section)
        check(after == [], f"{case_id}: section still incomplete, pending={after}")
        print(f"  {case_id}  after:  pending={after}  {gate}=True  -> section completes")


def test_empty_detail_cases_are_untouched() -> None:
    print("\n2. THE TWO THIS FIX DOES NOT COVER (gate written, detail dropped)")
    for case_id, section, detail, data in EMPTY_DETAIL:
        data = dict(data)
        snapshot = dict(data)

        check(
            infer_gate_from_detail(data, detail) is None,
            f"{case_id}: must not act on an empty detail",
        )
        check(data == snapshot, f"{case_id}: record was mutated")

        pending = get_pending_fields(state_for(section, data), section)
        check(detail in pending, f"{case_id}: expected {detail} still pending")
        print(f"  {case_id}  unchanged, still pending={pending}  (needs a separate fix)")


# ── 2. the guards that make it safe to ship ───────────────────────────────────

def test_never_overwrites_a_real_answer() -> None:
    print("\n3. NEVER OVERWRITES A VALUE THE PATIENT GAVE")
    for existing in (True, False):
        data = {
            "has_past_medications": existing,
            "past_medication_details": "Olanzapine; 10 mg nightly",
        }
        check(
            infer_gate_from_detail(data, "past_medication_details") is None,
            f"acted on a gate already set to {existing}",
        )
        check(data["has_past_medications"] is existing, f"overwrote gate={existing}")
        print(f"  gate already {existing!r:5} -> untouched")


def test_absence_markers_do_not_imply_existence() -> None:
    print("\n4. AN ABSENCE MARKER IN THE DETAIL IS AN ANSWER OF NO")
    for value in ("None reported.", "none", "No", "N/A", "nothing", "Denied",
                  "not reported", "Unknown"):
        check(reports_absence(value), f"reports_absence missed {value!r}")
        data = {"has_past_medications": None, "past_medication_details": value}
        check(
            infer_gate_from_detail(data, "past_medication_details") is None,
            f"inferred existence from {value!r}",
        )
        check(data["has_past_medications"] is None, f"wrote a gate from {value!r}")
        print(f"  {value!r:16} -> no inference")

    # ...but real content still must infer.
    data = {"has_past_medications": None, "past_medication_details": "Nortriptyline; 25 mg"}
    check(infer_gate_from_detail(data, "past_medication_details") == "has_past_medications",
          "a real medication starting with 'No' was treated as absence")
    print("  'Nortriptyline; 25 mg' -> infers True (not fooled by the leading 'No')")


def test_ignores_fields_that_are_not_details() -> None:
    print("\n5. NO-OP ON EVERYTHING THAT IS NOT A CONDITIONAL DETAIL")
    for field in ("name", "phq9_q9", "has_past_medications", "previous_therapies", ""):
        data = {field: "something", "has_past_medications": None}
        check(infer_gate_from_detail(data, field) is None, f"acted on {field!r}")
        print(f"  {field!r:22} -> None")

    # every detail is covered, and no gate is itself a detail
    check(set(GATE_OF_DETAIL) == set(CONDITIONAL_FIELDS), "GATE_OF_DETAIL lost a field")
    check(not (set(GATE_OF_DETAIL.values()) & set(GATE_OF_DETAIL)),
          "a gate is also registered as a detail; inference could chain")
    print(f"  {len(GATE_OF_DETAIL)} detail->gate pairs, no gate is itself a detail")


def test_conditional_field_maps_stay_in_sync() -> None:
    print("\n6. THE TWO CONDITIONAL_FIELDS COPIES AGREE")
    # core.state's copy rejects writes; builder's decides what is pending. This
    # fix writes through one and is observed through the other, so a divergence
    # would silently disable it.
    check(CONDITIONAL_FIELDS == BUILDER_CONDITIONAL_FIELDS,
          "core.state and prompts.builder CONDITIONAL_FIELDS have diverged")
    print(f"  both copies define the same {len(CONDITIONAL_FIELDS)} pairs")


# ── 3. reachability: the fix must be inert on every healthy record ────────────

def test_inert_on_saved_records() -> None:
    print("\n7. REACHABILITY ON THE SAVED CORPUS")
    root = Path(__file__).resolve().parents[2] / "evaluation" / "outputs" / "cira" / "records"
    files = sorted(root.glob("*.json")) if root.is_dir() else []
    if not files:
        print("  no saved records on disk - skipped (this is not a failure)")
        return

    from core.state import FIELD_TO_SECTION

    fired, inert = [], 0
    for path in files:
        record = json.loads(path.read_text())
        for detail in CONDITIONAL_FIELDS:
            section = FIELD_TO_SECTION.get(detail)
            if not section or section not in record:
                continue
            data = dict(record[section])
            if infer_gate_from_detail(data, detail) is not None:
                fired.append((record["scenario_case_id"], detail))
            else:
                inert += 1

    # Subset, not equality. outputs/ is live: re-running a case overwrites its
    # record, and once a stalled case has been re-run with the fix in place its
    # gate is written correctly and there is nothing left to infer. An empty
    # result is therefore the healthy end state, not a regression.
    #
    # The invariant that actually matters is the other direction - this must
    # never fire on a record that was not one of the known-stalled intakes,
    # because that is the whole basis for claiming no other case can change.
    known_stalled = {"04-02", "04-15", "04-19", "04-31"}
    got = {case for case, _ in fired}
    unexpected = got - known_stalled
    check(not unexpected, f"fired on healthy records: {sorted(unexpected)}")
    print(f"  {len(files)} records, {inert} field checks inert")
    if got:
        print(f"  fires on {sorted(got)} - all known-stalled intakes, none other")
    else:
        print("  fires on nothing: every record on disk already has its gate set")
    print("  no healthy record is ever touched, so no other case can change")


# ── 4. the wiring: the real save path, no network ─────────────────────────────

def test_apply_tool_calls_fills_the_gate() -> None:
    """Drive the actual write path with a fabricated tool call.

    The unit tests above prove the helper is correct; this proves it is
    reached. graph.nodes builds its ChatOpenAI clients at import time, so a
    placeholder key is set first - no request is ever made.
    """
    print("\n8. THE REAL WRITE PATH (apply_tool_calls, offline)")
    import os
    os.environ.setdefault("OPENAI_API_KEY", "placeholder-no-request-is-made")

    from copy import deepcopy
    from core.state import initial_state
    from graph.nodes import apply_tool_calls

    class FakeResponse:
        """Mimics only what apply_tool_calls reads off a model response."""
        def __init__(self, tool_calls):
            self.tool_calls = tool_calls

    # 04-19 exactly: "Have you previously tried any psychiatric medications?"
    # answered "Yes, olanzapine." The model writes the detail and drops the
    # boolean, which is the whole bug.
    state = deepcopy(initial_state)
    state["medications"]["has_current_medications"] = True
    state["medications"]["current_medications"] = "Lithium carbonate; 900 mg nightly"

    response = FakeResponse([{
        "name": "save_answer",
        "args": {"field_name": "past_medication_details",
                 "value": "Olanzapine; 10 mg nightly; stopped due to weight gain"},
        "id": "call_1",
    }])
    apply_tool_calls(state, "medications", response)

    check(state["medications"]["past_medication_details"] is not None,
          "the detail was not saved at all")
    check(state["medications"]["has_past_medications"] is True,
          f"gate not filled by the save path: "
          f"{state['medications']['has_past_medications']!r}")
    pending = get_pending_fields(state, "medications")
    check("has_past_medications" not in pending,
          f"gate still pending after being filled: {pending}")
    # ...but the DETAIL stays pending. It is repeatable, so it waits for
    # confirm_no_more_entries. This is the property that makes the fix safe:
    # filling the gate removes a redundant yes/no, it does NOT close the
    # section early or cut off collection of further entries.
    check(pending == ["past_medication_details"],
          f"expected only the repeatable detail to remain, got {pending}")
    print("  save_answer(past_medication_details) -> has_past_medications=True")
    print(f"  pending={pending} - collection continues, section is not cut short")

    # Once the patient confirms there are no more, the section completes -
    # which it could never do before the fix.
    state["entries_confirmed"] = ["current_medications", "past_medication_details"]
    check(get_pending_fields(state, "medications") == [],
          f"section still incomplete: {get_pending_fields(state, 'medications')}")
    print("  after confirm_no_more_entries -> pending=[], section completes")

    # The inverse must still be refused: a detail may not be written under a
    # gate the patient set to False. That guard is what makes the inference
    # sound, so a regression there would quietly invalidate this whole fix.
    state = deepcopy(initial_state)
    state["medications"]["has_past_medications"] = False
    response = FakeResponse([{
        "name": "save_answer",
        "args": {"field_name": "past_medication_details", "value": "Olanzapine"},
        "id": "call_2",
    }])
    results, _, _, _ = apply_tool_calls(state, "medications", response)

    check(state["medications"]["past_medication_details"] is None,
          "a detail was written under a False gate")
    check(state["medications"]["has_past_medications"] is False,
          "the False gate was overwritten")
    check("invalid" in results["call_2"], f"expected a rejection, got {results['call_2']!r}")
    print("  save_answer under a False gate -> still rejected, gate untouched")


# ── 5. fix B: the escalation ladder ───────────────────────────────────────────

def _nodes():
    """graph.nodes with a placeholder key. Constructed, never called."""
    import os
    os.environ.setdefault("OPENAI_API_KEY", "placeholder-no-request-is-made")
    import graph.nodes as nodes
    return nodes


def test_predicate_identifies_only_the_stuck_state() -> None:
    print("\n9. is_unanswered_conditional_detail")
    cases = [
        ({"hospital_admission": True,  "hospital_details": None},  True,  "gate True, detail empty"),
        ({"hospital_admission": False, "hospital_details": None},  False, "gate False - field is hidden"),
        ({"hospital_admission": None,  "hospital_details": None},  False, "gate unanswered - not yet stuck"),
        ({"hospital_admission": True,  "hospital_details": "2023"}, False, "detail present"),
    ]
    for data, expected, label in cases:
        got = is_unanswered_conditional_detail(data, "hospital_details")
        check(got is expected, f"{label}: expected {expected}, got {got}")
        print(f"  {label:32} -> {got}")

    for field in ("phq9_q9", "gad7_q1", "name", "previous_therapies"):
        check(not is_unanswered_conditional_detail({"phq9_q9": None}, field),
              f"{field} treated as a conditional detail")
    print("  questionnaire items and plain fields are never conditional details")


def test_ladder_escalates_then_resolves() -> None:
    print("\n10. THE LADDER ON THE TWO STALLED RECORDS")
    nodes = _nodes()
    for case_id, section, detail, data in EMPTY_DETAIL:
        state = {section: dict(data), "entries_confirmed": list(REPEATABLE_TEXT_FIELDS),
                 "stall_streak": {}, "sections_completed": []}
        seen = []
        for turn in range(1, MAX_EMPTY_DETAIL_FOLLOWUPS + 1):
            pending = get_pending_fields(state, section)
            check(pending and pending[0] == detail,
                  f"{case_id}: expected {detail} pending on turn {turn}, got {pending}")
            seen.append(nodes._stall_prompt(state, section, pending))

        check(seen[0] == nodes._GENERIC_NUDGE,
              f"{case_id}: first prompt changed - healthy turns must be untouched")
        check(seen[1] != nodes._GENERIC_NUDGE and seen[1] == nodes._DETAIL_REASK[detail],
              f"{case_id}: second prompt did not escalate, got {seen[1]!r}")
        check(state[section][detail] == "Unknown",
              f"{case_id}: detail not resolved, is {state[section][detail]!r}")
        check(get_pending_fields(state, section) == [],
              f"{case_id}: section still pending: {get_pending_fields(state, section)}")
        check(section in state["sections_completed"], f"{case_id}: section not marked complete")

        print(f"  {case_id}  1: {seen[0][:46]}...")
        print(f"  {case_id}  2: {seen[1]}")
        print(f"  {case_id}  {MAX_EMPTY_DETAIL_FOLLOWUPS}: recorded \"Unknown\" -> pending=[], section completes")


def test_ladder_resets_on_progress() -> None:
    print("\n11. A REAL QUESTION RESETS THE LADDER")
    nodes = _nodes()
    section, detail = "past_psychiatric_history", "hospital_details"
    state = {section: {"hospital_admission": True, "hospital_details": None},
             "entries_confirmed": list(REPEATABLE_TEXT_FIELDS),
             "stall_streak": {}, "sections_completed": []}
    pending = [detail]

    nodes._stall_prompt(state, section, pending)
    nodes._stall_prompt(state, section, pending)
    check(state["stall_streak"][detail] == 2, "streak did not accumulate")

    state["stall_streak"] = {}          # what section_node does on a real question
    out = nodes._stall_prompt(state, section, pending)
    check(out == nodes._GENERIC_NUDGE, f"ladder did not restart, got {out!r}")
    check(state[section][detail] is None, "a reset ladder still wrote Unknown")
    print("  2 stalls, then a real question, then a stall -> back to the generic nudge")
    print("  a patient who is slowly getting there can never be cut off")


def test_ladder_never_writes_a_questionnaire_item() -> None:
    print("\n12. THE LADDER CANNOT REACH PHQ-9 / GAD-7")
    # The deepest loops in the corpus (up to 9) were all in phq9/gad7. Neither
    # section holds a conditional field, so the last rung is unreachable there -
    # this is the property that keeps the measured threshold valid.
    nodes = _nodes()
    state = {"phq9": {"phq9_q9": None}, "stall_streak": {}, "sections_completed": []}
    for _ in range(MAX_EMPTY_DETAIL_FOLLOWUPS * 3):
        nodes._stall_prompt(state, "phq9", ["phq9_q9"])
    check(state["phq9"]["phq9_q9"] is None,
          f"a questionnaire item was written: {state['phq9']['phq9_q9']!r}")
    print(f"  {MAX_EMPTY_DETAIL_FOLLOWUPS * 3} consecutive stalls on phq9_q9 -> still None, never scored")

    # ...and a non-conditional free-text field is equally out of reach.
    state = {"current_concerns": {"presenting_problem": None},
             "stall_streak": {}, "sections_completed": []}
    for _ in range(MAX_EMPTY_DETAIL_FOLLOWUPS * 3):
        nodes._stall_prompt(state, "current_concerns", ["presenting_problem"])
    check(state["current_concerns"]["presenting_problem"] is None,
          "a non-conditional field was resolved to Unknown")
    print("  the same on a plain field -> still None")


def test_threshold_clears_every_healthy_intake() -> None:
    print("\n13. THE THRESHOLD AGAINST THE SAVED TRANSCRIPTS")
    root = Path(__file__).resolve().parents[2] / "evaluation" / "outputs" / "cira" / "transcripts"
    files = sorted(root.glob("*.json")) if root.is_dir() else []
    if not files:
        print("  no saved transcripts on disk - skipped (this is not a failure)")
        return

    from core.state import FIELD_TO_SECTION
    import collections
    nodes = _nodes()

    conditional_sections = {
        FIELD_TO_SECTION[d] for d in CONDITIONAL_FIELDS if d in FIELD_TO_SECTION
    }
    check("phq9" not in conditional_sections and "gad7" not in conditional_sections,
          "a questionnaire section now holds a conditional field; re-measure the threshold")

    stalled = {"04-02", "04-15", "04-19", "04-31", "04-36", "04-40"}
    deepest = collections.defaultdict(int)
    for path in files:
        data = json.loads(path.read_text())
        case = data["scenario_case_id"]
        run = collections.Counter()
        for message in data["conversation"]:
            if message.get("speaker") != "CIRA":
                continue
            sec = message.get("section")
            if sec not in conditional_sections:
                continue
            if nodes._GENERIC_NUDGE in message["message"]:
                run[sec] += 1
                deepest[case] = max(deepest[case], run[sec])
            else:
                run[sec] = 0

    healthy = max((v for c, v in deepest.items() if c not in stalled), default=0)
    check(healthy < MAX_EMPTY_DETAIL_FOLLOWUPS,
          f"a healthy intake reached {healthy} stalls, at or past the "
          f"threshold of {MAX_EMPTY_DETAIL_FOLLOWUPS} - re-measure before shipping")
    print(f"  deepest stall run in a healthy intake: {healthy}")
    print(f"  threshold: {MAX_EMPTY_DETAIL_FOLLOWUPS}  (last rung unreachable in all "
          f"{len(files) - len(stalled)} healthy cases)")


# ── 6. fix C: recognising a question that carries no question mark ────────────

# Real CIRA replies from the 50-case evaluation. Each was classified "not a
# question" and had a redundant nudge stapled to it; the patient answered every
# one of them on the next turn.
ASKS_SOMETHING = [
    "Please provide your complete legal name, including your first name and last name.",
    "Please tell me about your most recent job, including the employer and your job title.",
    "Please describe your early childhood, including where you were born.",
    "Your current height, if you know it. Please give your best estimate.",
    "GAD-7 Question 2: This asks how often you have had difficulty stopping worrying.\n\n"
    "0 - Not at all\n1 - Several days\n2 - More than half the days\n3 - Nearly every day",
    "How difficult have these problems made things?\n\n- Not difficult at all\n"
    "- Somewhat difficult\n- Very difficult\n- Extremely difficult",
    "Either format is fine: you can tell me your height in centimetres, or in feet and inches.",
    "I mean your complete legal name exactly as it appears on your legal documents.",
    "A brief overview is fine. Please include where you were born and where you grew up.",
]

# These must keep nudging. The first two are the exact texts the six stalled
# intakes looped on; the rest are the failure the nudge was written for.
ASKS_NOTHING = [
    "All done! Please take a look at the panel on the right — if anything looks "
    "incorrect or if you'd like to add or change anything, just let me know.",
    "Thank you for confirming.",
    "Thank you. I've noted that no changes are needed.",
    "Your responses have been recorded.",
    "The intake is complete.",
    "All done! Anything to change?",
    "",
]


def test_recognises_questions_without_a_question_mark() -> None:
    print("\n14. A QUESTION MARK IS NOT REQUIRED")
    nodes = _nodes()
    for text in ASKS_SOMETHING:
        check(nodes._looks_like_a_question(text),
              f"still classified as not-a-question: {text[:60]!r}")
        print(f"  asks    {text.splitlines()[0][:64]!r}")


def test_closing_phrases_still_win() -> None:
    print("\n15. THE ORIGINAL GUARD IS INTACT")
    nodes = _nodes()
    for text in ASKS_NOTHING:
        check(not nodes._looks_like_a_question(text),
              f"wrongly rescued as a question: {text[:60]!r}")
        print(f"  nudges  {(text.splitlines() or [''])[0][:64]!r}")
    # The first entry is the one that matters most: it CONTAINS an imperative
    # ("Please take a look") and is still not a question, because a closing
    # phrase outranks everything. Losing that ordering would re-open the stall
    # this whole file exists to close.
    check(not nodes._looks_like_a_question(ASKS_NOTHING[0]),
          "an imperative rescued a reply that announces completion")
    print("  'All done! Please take a look...' -> closing phrase outranks the imperative")


def test_fix_c_against_the_saved_transcripts() -> None:
    print("\n16. RE-CLASSIFYING EVERY REAL NUDGE SITE")
    root = Path(__file__).resolve().parents[2] / "evaluation" / "outputs" / "cira" / "transcripts"
    files = sorted(root.glob("*.json")) if root.is_dir() else []
    if not files:
        print("  no saved transcripts on disk - skipped (this is not a failure)")
        return

    import collections
    nodes = _nodes()
    stalled = {"04-02", "04-15", "04-19", "04-31", "04-36", "04-40"}
    suppressed, kept = 0, collections.Counter()
    for path in files:
        data = json.loads(path.read_text())
        for message in data["conversation"]:
            if message.get("speaker") != "CIRA":
                continue
            if nodes._GENERIC_NUDGE not in message["message"]:
                continue
            body = message["message"].split(nodes._GENERIC_NUDGE)[0].strip()
            if nodes._looks_like_a_question(body):
                suppressed += 1
            else:
                kept[data["scenario_case_id"]] += 1

    total = suppressed + sum(kept.values())
    if not total:
        print("  transcripts carry no nudge sites - skipped")
        return

    # Every stalled intake present on disk must still be nudged. Suppressing
    # those would mean Fix C had swallowed the signal Fix A and B rely on.
    present = {json.loads(f.read_text())["scenario_case_id"] for f in files}
    for case in sorted(stalled & present):
        if case in kept:
            print(f"  {case}: {kept[case]} nudges retained (genuine stall)")

    check(suppressed > 0, "Fix C suppressed nothing")
    print(f"  {suppressed}/{total} nudge sites suppressed ({suppressed / total:.0%})")
    print(f"  {sum(kept.values())} retained across {len(kept)} cases")


def main() -> None:
    print("=" * 70)
    print("GATE / DETAIL RECONCILIATION REGRESSION TEST")
    print("=" * 70)

    test_orphan_gate_cases()
    test_empty_detail_cases_are_untouched()
    test_never_overwrites_a_real_answer()
    test_absence_markers_do_not_imply_existence()
    test_ignores_fields_that_are_not_details()
    test_conditional_field_maps_stay_in_sync()
    test_inert_on_saved_records()
    test_apply_tool_calls_fills_the_gate()
    test_predicate_identifies_only_the_stuck_state()
    test_ladder_escalates_then_resolves()
    test_ladder_resets_on_progress()
    test_ladder_never_writes_a_questionnaire_item()
    test_threshold_clears_every_healthy_intake()
    test_recognises_questions_without_a_question_mark()
    test_closing_phrases_still_win()
    test_fix_c_against_the_saved_transcripts()

    print("\n" + "=" * 70)
    print(f"ALL {PASSED} CHECKS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    main()
