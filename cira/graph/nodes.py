import re

from langchain_openai import ChatOpenAI

from core.config import MODEL_NAME, TEMPERATURE
from core.languages import (
    PROPER_NOUN_FIELDS,
    all_frequency_phrases,
    all_question_marks,
    non_latin_script,
)
from core.state import (
    AliceState,
    CONDITIONAL_FIELDS,
    FIELD_TO_SECTION,
    MAX_REPEATABLE_FOLLOWUPS,
    REPEATABLE_TEXT_FIELDS,
    REQUIRED_FIELDS,
    MAX_EMPTY_DETAIL_FOLLOWUPS,
    infer_gate_from_detail,
    is_unanswered_conditional_detail,
    reports_absence as _reports_absence,
)
from core.tools import tools
from core.validators import FIELD_VALIDATORS
from core.safety import explicit_safety_trigger, SAFETY_REPLY
from core.languages import safety_reply_for
from core.scoring import calculate_phq9_total, calculate_gad7_total
from core.storage import save_record
from prompts.builder import build_system_prompt, get_pending_fields


# temperature is passed explicitly on both clients. See core.config.TEMPERATURE:
# omitting it silently ran CIRA at the provider default while every other
# component in the evaluation was pinned.
model = ChatOpenAI(
    model=MODEL_NAME, temperature=TEMPERATURE, reasoning_effort="none"
).bind_tools(tools)
llm   = ChatOpenAI(
    model=MODEL_NAME, temperature=TEMPERATURE, reasoning_effort="none"
)


def _merge_repeatable_value(existing, incoming):
    """Never let a repeatable free-text field lose an already-saved entry."""
    if not existing:
        return incoming
    if not incoming:
        return existing

    incoming_norm = " ".join(str(incoming).split()).lower()
    preserved = []
    for entry in re.split(r"\.\s+", str(existing)):
        entry = entry.strip()
        if not entry:
            continue
        # An entry's identity is the text before its first field separator
        # ("Citalopram; 20 mg ..." -> "citalopram"). If that identity is absent
        # from the new value, the model dropped the entry; keep it.
        name = entry.split(";")[0].strip().lower()
        if name and name not in incoming_norm:
            preserved.append(entry)

    if preserved:
        return str(incoming).rstrip(". ") + ". " + ". ".join(preserved)
    return incoming


# ── Guards against recording an answer the patient never gave ─────────────────

QUESTIONNAIRE_ITEM = re.compile(r"^(?:phq9|gad7)_q\d+$")

# Wordings that constitute an actual selection on the 0-3 frequency scale.
#
# The English list also carries loose paraphrases ("most days", "all the time")
# that a patient reaches for instead of the printed option. The per-language
# phrases come from the registry, so a Mandarin or Arabic patient answering with
# the printed option is recognised too - without them, a correctly answered item
# was rejected as "no option selected" and the interview re-asked it forever.
_SCALE_RESPONSES = (
    "not at all", "several days", "more than half", "nearly every day",
    "never", "every day", "most days", "a few days", "some days",
    "half the days", "all the time",
) + all_frequency_phrases()

# The patient asking for help is not the patient finishing a list.
_CLARIFICATION_MARKERS = (
    "could you ask", "can you ask", "could you say", "can you say",
    "one at a time", "ask it again", "say it again", "a different way",
    "more simply", "i'm not sure what you mean", "i don't follow",
)


def _last_patient_message(state: AliceState) -> str:
    for message in reversed(state.get("messages") or []):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def _patient_selected_a_scale_option(state: AliceState) -> bool:
    """Did the patient's last message actually pick a frequency option?

    Without this the model could record a score for an item the patient never
    answered: after two deflections on PHQ-9 Question 2 it moved on and saved 0,
    which read as a genuine negative and pulled the total from 3 down to 2. An
    unanswered clinical item must stay unanswered, not default to zero.
    """
    text = _last_patient_message(state).lower()
    if not text:
        return False
    if re.search(r"(?<![\w.])[0-3](?![\w.])", text):
        return True
    return any(token in text for token in _SCALE_RESPONSES)


def _patient_is_asking_for_help(state: AliceState) -> bool:
    """The patient is requesting clarification rather than closing a list."""
    text = _last_patient_message(state).lower().strip()
    if any(marker in text for marker in _CLARIFICATION_MARKERS):
        return True
    return text.endswith("?")


def _confirm_entries(state: AliceState, field: str) -> None:
    confirmed = state.setdefault("entries_confirmed", [])
    if field not in confirmed:
        confirmed.append(field)


def _implicitly_confirm_earlier_fields(state: AliceState, section: str, saved_field: str) -> None:
    """Saving a LATER field confirms the repeatable fields before it.

    If the model has moved on to the next field in the section, it is done with
    the earlier ones. Treating that as confirmation stops an intake stalling
    forever on a model that never calls confirm_no_more_entries, without
    requiring the harness to guess.
    """
    order = REQUIRED_FIELDS.get(section, [])
    if saved_field not in order:
        return
    cutoff = order.index(saved_field)
    for earlier in order[:cutoff]:
        if (
            earlier in REPEATABLE_TEXT_FIELDS
            and state[section].get(earlier) is not None
        ):
            _confirm_entries(state, earlier)


def _auto_confirm_exhausted_followups(
    state: AliceState, section: str, values_before: dict | None = None
) -> None:
    """Safety valve: close a repeatable field that is going nowhere.

    Counts only CONSECUTIVE UNPRODUCTIVE turns - the counter resets whenever the
    field's value changed this turn, i.e. the interview elicited something. An
    earlier version counted every turn the field was pending, so a field being
    actively and successfully worked through was closed after three asks and the
    remaining entries were lost.
    """
    followups = state.setdefault("repeatable_followups", {})
    confirmed = set(state.get("entries_confirmed") or [])
    values_before = values_before or {}

    for field in REQUIRED_FIELDS.get(section, []):
        if field not in REPEATABLE_TEXT_FIELDS:
            continue
        if field in confirmed or state[section].get(field) is None:
            continue

        if state[section].get(field) != values_before.get(field):
            followups[field] = 0      # progress: start the count again
            continue

        followups[field] = followups.get(field, 0) + 1
        if followups[field] >= MAX_REPEATABLE_FOLLOWUPS:
            _confirm_entries(state, field)


def handle_safety(state: AliceState) -> AliceState:
    """Raise the safety flag once while preserving the original conversation."""
    already_raised = bool(state.get("safety_flag"))
    state["safety_flag"] = True

    if not already_raised:
        state["messages"] = state["messages"] + [
            {"role": "assistant", "content": _safety_reply(state)}
        ]

    update_completion(state, state["current_section"])
    state["conversation_started"] = True
    save_record(state)
    return state


def apply_tool_calls(state: AliceState, section: str, response):
    """Process tool calls. Returns (tool_results, safety_raised, touched_sections)."""
    tool_results     = {}
    values_saved     = set()
    safety_raised    = False
    touched_sections = {section}

    for tc in response.tool_calls:
        if tc["name"] == "save_answer":
            field = tc["args"]["field_name"]
            value = tc["args"]["value"]

            # Route the write by FIELD NAME, not by the section that happens to
            # be active. A patient volunteering something out of order is normal
            # (and the "confused" persona is built to do it); writing it into
            # the current section's dict corrupted the record, left the real
            # field empty, and looked like a fabricated field downstream.
            target_section = FIELD_TO_SECTION.get(field)
            if target_section is None:
                tool_results[tc["id"]] = (
                    f"invalid: unknown field '{field}'. Use an exact intake field name."
                )
                continue
            touched_sections.add(target_section)

            # A questionnaire score may only be recorded when the patient
            # actually selected an option this turn.
            if QUESTIONNAIRE_ITEM.match(field) and not _patient_selected_a_scale_option(state):
                tool_results[tc["id"]] = (
                    f"invalid: the patient has not selected an option for {field}. "
                    "Do not record a score. Re-ask the SAME item, restating its "
                    "full label and the four options, and do not move to the next "
                    "item until they choose one."
                )
                continue

            # A conditional field cannot be written while its controlling
            # boolean says the thing does not exist. This is the guard that was
            # missing in case 04-05: a stopped medication was saved into
            # current_medications even though has_current_medications was False,
            # producing a fabricated field that no record metric catches (the
            # field has null ground truth, so it is excluded from the
            # denominator - only the fabrication count sees it).
            dependency = CONDITIONAL_FIELDS.get(field)
            if dependency:
                parent, hidden_value = dependency
                if state[target_section].get(parent) is hidden_value:
                    tool_results[tc["id"]] = (
                        f"invalid: {field} cannot be set while {parent} is "
                        f"{hidden_value}. If this information belongs to the "
                        f"patient, set {parent} first; if it is a PAST item, "
                        f"save it in the corresponding past/history field "
                        f"instead. Do not record the same item as both current "
                        f"and past."
                    )
                    continue

            # The record must be in English whatever the conversation language,
            # because the record judge compares a produced value against English
            # ground truth: a field left in Mandarin scores as wrong even when
            # the intake understood it perfectly. Telling the model was not
            # enough - a live Mandarin run stored 3 of 14 text fields in
            # Chinese, including primary_problems and goals - so it is enforced
            # here, the same way every other invalid write is.
            rejected = _reject_non_english(state, field, value, tool_results, tc)
            if rejected:
                continue

            validator   = FIELD_VALIDATORS.get(field)
            saved_value = None

            if validator:
                valid, result = validator(value)
                if valid:
                    state[target_section][field] = result
                    saved_value = result
                    tool_results[tc["id"]] = "saved"
                else:
                    tool_results[tc["id"]] = f"invalid: {result}"
            else:
                if field in REPEATABLE_TEXT_FIELDS:
                    value = _merge_repeatable_value(
                        state[target_section].get(field), value
                    )
                state[target_section][field] = value
                saved_value = value
                tool_results[tc["id"]] = "saved"

            if saved_value is not None:
                values_saved.add(field)
                # A detail cannot exist unless the thing it details exists. When
                # the patient answered the gate question with content instead of
                # a bare yes, the boolean was never written and the section
                # could never complete. See infer_gate_from_detail.
                infer_gate_from_detail(state[target_section], field)
                _implicitly_confirm_earlier_fields(state, target_section, field)
                if field in REPEATABLE_TEXT_FIELDS and _reports_absence(saved_value):
                    _confirm_entries(state, field)

            # PHQ-9 question 9 is a deterministic safety rule.
            # Any successfully saved score above zero raises the flag, even when
            # the patient's raw reply is only "Several days".
            if target_section == "phq9" and field == "phq9_q9" and saved_value is not None:
                try:
                    q9_score = int(saved_value)
                except (TypeError, ValueError):
                    q9_score = 0
                if q9_score > 0 and not state.get("safety_flag", False):
                    safety_raised = True

        elif tc["name"] == "confirm_no_more_entries":
            field = tc["args"].get("field_name")
            # Closing a repeatable field while the patient is still asking for
            # clarification discards the entries they were about to give. Family
            # history lost a mother and a grandfather exactly this way.
            if field in REPEATABLE_TEXT_FIELDS and _patient_is_asking_for_help(state):
                tool_results[tc["id"]] = (
                    f"invalid: the patient is still asking for clarification about "
                    f"{field}. Answer their question and ask again; only confirm "
                    "once they clearly state there are no more entries."
                )
            elif field in REPEATABLE_TEXT_FIELDS:
                _confirm_entries(state, field)
                target_section = FIELD_TO_SECTION.get(field)
                if target_section:
                    touched_sections.add(target_section)
                tool_results[tc["id"]] = "confirmed"
            else:
                tool_results[tc["id"]] = (
                    f"invalid: '{field}' is not a repeatable field."
                )

        elif tc["name"] == "raise_safety_flag":
            # Defer the state mutation to the reply stage, which appends the
            # safety text exactly once.
            if not state.get("safety_flag", False):
                safety_raised = True
                tool_results[tc["id"]] = "flag_raised"
            else:
                tool_results[tc["id"]] = "flag_already_raised"

    return tool_results, safety_raised, touched_sections, values_saved


def update_completion(state: AliceState, section: str):
    """Add/remove the section from completed based on pending fields."""
    pending = get_pending_fields(state, section)

    if pending:
        if section in state["sections_completed"]:
            state["sections_completed"].remove(section)
    elif section not in state["sections_completed"]:
        state["sections_completed"].append(section)


def section_node(state: AliceState) -> AliceState:
    section = state["current_section"]

    # ── Stage 1: deterministic safety gate on raw patient text ──
    #
    # This used to `return handle_safety(state)` immediately, which meant the
    # model never saw the message: whatever intake field the patient was
    # answering in that same message was silently lost, the state's last message
    # became the safety text (which contains no question), and the driver read
    # that as CIRA's next question. One lost answer, one wasted turn, one
    # non-question, and a duplicate re-ask.
    #
    # The flag is now raised here and the turn continues normally, so the
    # message is still processed and the safety text is prepended to a real
    # reply - matching what the raise_safety_flag tool path already did.
    deterministic_safety = False
    if (
        not state.get("safety_flag", False)
        and state["messages"]
        and state["messages"][-1].get("role") == "user"
    ):
        if explicit_safety_trigger(state["messages"][-1]["content"]):
            deterministic_safety = True
            state["safety_flag"] = True

    # ── Stage 2: call the model ──
    system   = {"role": "system", "content": build_system_prompt(state)}
    response = model.invoke([system] + state["messages"])

    # Snapshot before the tool calls so the valve below can tell a productive
    # turn from an unproductive one.
    values_before = {
        field: state[section].get(field)
        for field in REQUIRED_FIELDS.get(section, [])
        if field in REPEATABLE_TEXT_FIELDS
    }

    # ── Stage 3: process tool calls ──
    tool_results, safety_raised, touched_sections, values_saved = apply_tool_calls(
        state, section, response
    )

    # ── Stage 4: scoring for any questionnaire section that was written ──
    if "phq9" in touched_sections:
        state["phq9"]["phq9_total"] = calculate_phq9_total(state)
    if "gad7" in touched_sections:
        state["gad7"]["gad7_total"] = calculate_gad7_total(state)

    # ── Stage 4b: remember that a self-harm history was cleared ──
    #
    # Saving self_harm_details without raising the flag on the same turn means
    # the disclosure was assessed and found to be historical. Recording that
    # lets later sections know it has already been adjudicated, which the
    # per-section message reset would otherwise erase.
    if (
        "self_harm_details" in values_saved
        and not safety_raised
        and not deterministic_safety
        and not state.get("safety_flag")
    ):
        state["safety_history_cleared"] = True

    # ── Stage 5: bound the "any more entries?" follow-ups ──
    _auto_confirm_exhausted_followups(state, section, values_before)

    # ── Stage 6: build the reply ──
    if not response.tool_calls:
        reply         = response.content
        tool_exchange = []
    else:
        tool_exchange  = [response] + [
            {"role": "tool", "content": tool_results[tc["id"]], "tool_call_id": tc["id"]}
            for tc in response.tool_calls
            if tc["id"] in tool_results
        ]
        updated_system = {"role": "system", "content": build_system_prompt(state)}
        reply          = llm.invoke(
            [updated_system] + state["messages"] + tool_exchange
        ).content

    if (safety_raised or deterministic_safety) and not _safety_text_already_sent(state):
        state["safety_flag"] = True
        reply = _safety_reply(state) + "\n\n" + (reply or "")
        state["safety_text_sent"] = True

    # A reply must carry a question whenever the section still has pending
    # fields. Two failures made this necessary, both observed on a real case:
    #
    #   1. An empty assistant turn stalls the driver, which reads the last
    #      message as the next question.
    #   2. When the safety flag is raised on the SAME turn as a question, the
    #      crisis text can displace that question. The patient then answers
    #      nothing, the field stays open, and the model - believing it is
    #      finished - emits "All done!" and filler until the stall guard ends
    #      the section. On case 04-03 that cost phq9_difficulty and the whole
    #      phq9 section, on a clear-persona patient.
    pending = get_pending_fields(state, section)
    if not (reply or "").strip():
        reply = _pending_field_question(pending)
    elif pending and not _looks_like_a_question(reply):
        # Announcing completion while a field is open is the tell. Append the
        # pending question rather than replacing the text, so a safety message
        # is still delivered in full.
        # _stall_prompt may resolve the field it is stuck on; Stage 7 below
        # re-runs update_completion for this section either way.
        reply = reply.rstrip() + "\n\n" + _stall_prompt(state, section, pending)
    else:
        # A real question is progress; the ladder starts from the bottom again.
        state["stall_streak"] = {}

    # ── Stage 7: completion for every section this turn touched ──
    for touched in touched_sections:
        update_completion(state, touched)
    save_record(state)

    # ── Stage 8: commit messages ──
    state["messages"] = (
        state["messages"] + tool_exchange + [{"role": "assistant", "content": reply}]
    )
    state["conversation_started"] = True
    return state


# Completion phrases the model reaches for when it wrongly believes a section
# is finished. Used only to decide whether a pending question must be appended.
_CLOSING_PHRASES = (
    "all done", "intake is complete", "responses have been recorded",
    "i'm here if you need", "i am here if you need", "i'm here to help",
    "i am here to help", "no further information", "available if you have",
    "thank you for completing", "that completes",

    # Completion phrasings outside English. A DELIBERATELY SMALL, high-confidence
    # set: these decide whether a reply that ends in a question mark is treated
    # as a real question, and a wrong entry here suppresses a genuine question.
    #
    # Coverage outside English is therefore lower than inside it, and that is an
    # accepted limitation rather than an oversight. It degrades safely: when a
    # completion phrase is missed the pending-field nudge is simply not appended,
    # the field stays in the prompt, and the model usually asks on the next turn.
    # The driver's stall guard, the gate inference and the empty-detail ladder all
    # act on the ENGLISH record, so section completion is still protected.
    # 中文
    "全部完成", "已完成", "记录完毕", "问诊结束", "已记录",
    # Français
    "tout est terminé", "c'est terminé", "l'entretien est terminé",
    "vos réponses ont été enregistrées",
    # العربية
    "تم الانتهاء", "انتهى التقييم", "تم تسجيل", "اكتمل",
    # हिन्दी
    "पूरा हो गया", "सब कुछ दर्ज", "मूल्यांकन पूरा",
    # فارسی
    "تمام شد", "به پایان رسید", "ثبت شد", "کامل شد",
)


# Questionnaire item keys must never appear in patient-facing text. Rendering
# "gad7_q1" as "gad7 q1" produced a message containing "q1", which the patient
# simulator's bare-question-number pattern matched - a GAD-7 item resolved to
# phq9_q1 and the entire GAD-7 record became a copy of the PHQ-9 record. It also
# reads as nonsense to a patient, which is reason enough on its own.
_QUESTIONNAIRE_KEY = re.compile(r"^(?:phq9|gad7)_(?:q\d+|difficulty)$")


# The wording of the first stall prompt, unchanged from when it was inlined.
# Every healthy turn that needs a nudge still gets exactly this, so the common
# path is untouched.
_GENERIC_NUDGE = "Before we move on, could you answer the question above?"


# Patient-facing phrasing for the conditional details, used once the generic
# nudge has already failed. _pending_field_question falls back to the raw field
# name, which renders as "Could you tell me about hospital details?" - the same
# class of leak the questionnaire guard below exists to prevent, and clumsy
# enough on its own to be worth avoiding on a re-ask that is already awkward.
_DETAIL_REASK = {
    "family_doctor_name":      "What is your family doctor's name?",
    "psychiatrist_name":       "What is your psychiatrist's name?",
    "assessment_details":      "When were you assessed, and by whom?",
    "hospital_details":        "What year were you admitted, where, and how long was the stay?",
    "self_harm_details":       "Could you briefly describe what happened?",
    "current_medications":     "What is the name of one medication you are currently taking?",
    "past_medication_details": "What is the name of one psychiatric medication you have taken before?",
    "medical_conditions":      "What medical condition have you been diagnosed with?",
    "surgical_history":        "What surgery have you had, and roughly when?",
    "medication_allergies":    "Which medication are you allergic to, and what happens?",
    "family_psychiatric_history_details":
                               "Which family member, and what were they diagnosed with?",
    "legal_case_details":      "Could you tell me about the legal matter?",
}


def _stall_prompt(state: AliceState, section: str, pending: list) -> str:
    """The stall prompt, escalating each time it fails on the same field.

    The generic nudge points at "the question above". After it has failed once
    that question is one the patient has already answered - often several times
    - so repeating it verbatim cannot break the deadlock. Eight consecutive
    copies of it is what the flow judge quoted back on the stalled intakes, and
    what burned the section turn budget until the driver's stall guard fired.

    The ladder:

      1st  the generic nudge, byte-identical to before. A single stall is
           normal and usually self-corrects, so the common case is unchanged.
      2nd+ a specific question naming the field that is actually missing.
      4th  for an empty conditional detail only, record "Unknown" and move on.

    The last rung is deliberately narrow. It fires only for a detail whose own
    gate says it exists, because that is the one state no other valve can clear
    and the only one that can hold a section open indefinitely. Anything else -
    a questionnaire item above all - escalates to a better question and stops
    there; no rung of this ladder can write a PHQ-9 or GAD-7 score.

    "Unknown" is not invented: the section prompts already instruct the model to
    record exactly that for a detail the patient cannot supply.
    """
    field = pending[0] if pending else None
    if field is None:
        state["stall_streak"] = {}
        return _GENERIC_NUDGE

    streak = state.get("stall_streak") or {}
    count = streak.get(field, 0) + 1
    state["stall_streak"] = {field: count}

    if count == 1:
        return _GENERIC_NUDGE

    if (
        count >= MAX_EMPTY_DETAIL_FOLLOWUPS
        and is_unanswered_conditional_detail(state[section], field)
    ):
        # The interview cannot reach this one. Record it as unknown rather than
        # lose the rest of the section to it, and say so plainly - the patient
        # should never be left thinking an answer was captured when it was not.
        state[section][field] = "Unknown"
        state["stall_streak"] = {}
        update_completion(state, section)
        return (
            "I was not able to record that detail, so I have noted it as "
            "unknown. We can come back to it later if you remember more."
        )

    return _DETAIL_REASK.get(field) or _pending_field_question(pending)


def _pending_field_question(pending: list) -> str:
    """A patient-facing prompt for the next pending field."""
    if not pending:
        return "Is there anything else you would like to add or change?"
    field = pending[0]
    if _QUESTIONNAIRE_KEY.match(field):
        # The item text is already on screen; point at it rather than name it.
        return "Could you choose one of the options above for that question?"
    return f"Could you tell me about {field.replace('_', ' ')}?"


# CIRA asks for most fields imperatively - "Please provide your phone number,
# including the area code" - and never punctuates those with a question mark.
_IMPERATIVE_REQUEST = re.compile(
    r"\b(?:please|kindly)\s+(?:\w+\s+){0,2}?"
    r"(?:provide|describe|tell|list|share|state|give|choose|select|confirm|"
    r"specify|name|enter|indicate|answer|report)\b"
)

# A questionnaire item is a statement followed by its option list, so it carries
# no question mark either. Both option sets are matched by their first and last
# option in order, which is unambiguous and cannot be produced by prose.
# When the patient is confused, CIRA restates the question as an offer rather
# than an interrogative - "Either format is fine: you can tell me your height in
# centimetres, or in feet and inches." That is the recovery behaviour the flow
# rubric asks for, and it was being nudged for its trouble.
_CLARIFYING_RESTATEMENT = re.compile(
    r"\byou can (?:tell me|start with|state|give|share|say|use|list|include)\b"
    r"|\bi mean\b"
    r"|\bplease include\b"
    r"|\b(?:either|any) (?:one|order|format|is fine)\b"
)

_QUESTION_MARKS = all_question_marks()

_SCALE_PROMPT = re.compile(r"not at all\b.*\bnearly every day")
_DIFFICULTY_PROMPT = re.compile(r"not difficult at all\b.*\bextremely difficult")


def _looks_like_a_question(reply: str) -> bool:
    """True when the reply actually asks the patient something.

    A question mark alone is not enough: "All done! Anything to change?" reads
    as a question but asks nothing about the pending field. Closing phrases are
    therefore treated as non-questions even when punctuated as one.

    A question mark is not *necessary* either, which is the more expensive half.
    Requiring one classified 281 of the 284 stall prompts in the 50-case
    evaluation as "not a question" - they were imperative requests and
    questionnaire items that the patient went on to answer normally. Each one
    had a redundant "could you answer the question above?" stapled to a question
    it was already answering, and the flow judge quoted that phrase back as
    robotic and mechanical across the corpus, mostly on healthy intakes.

    Order matters: a closing phrase still wins over everything, so "All done!
    Please take a look at the panel" is not rescued by its imperative.
    """
    text = " ".join(str(reply or "").split()).lower()
    if not text:
        return False
    if any(phrase in text for phrase in _CLOSING_PHRASES):
        return False
    # Any script's question mark. Mandarin punctuates with U+FF1F and Arabic and
    # Farsi with U+061F, so testing only for "?" read every non-English question
    # as a statement and appended a redundant nudge to it.
    if any(mark in text for mark in _QUESTION_MARKS):
        return True
    return bool(
        _IMPERATIVE_REQUEST.search(text)
        or _CLARIFYING_RESTATEMENT.search(text)
        or _SCALE_PROMPT.search(text)
        or _DIFFICULTY_PROMPT.search(text)
    )


#: How many times one field's value may be rejected for not being English.
#: Bounded on purpose: a model that will not comply must not be able to stall the
#: intake forever. After this many tries the value is accepted as given and the
#: leak is left visible in the record, where the comparison tool counts it -
#: losing the answer entirely would be worse than storing it in the wrong
#: language.
MAX_ENGLISH_REJECTIONS = 2


def _reject_non_english(state: AliceState, field: str, value, tool_results, tc) -> bool:
    """Refuse a non-English value, up to a bounded number of times.

    Returns True when the write was refused. Proper nouns are exempt: a person's
    name, their street or their email is kept as they gave it, and "translating"
    those would corrupt the record rather than fix it.

    Only a CHANGE OF SCRIPT is detected, so a French answer left in French is not
    caught - "Féminin" is Latin. That gap is reported as a limitation rather than
    papered over; it needs a reader, not a code point range.
    """
    if field in PROPER_NOUN_FIELDS:
        return False
    script = non_latin_script(value)
    if not script:
        return False

    counts = state.setdefault("english_record_rejections", {})
    if counts.get(field, 0) >= MAX_ENGLISH_REJECTIONS:
        return False          # accept it; the leak stays visible in the record

    counts[field] = counts.get(field, 0) + 1
    tool_results[tc["id"]] = (
        f"invalid: {field} was written in {script}. The clinical record is "
        f"always English, whatever language you are speaking to the patient in. "
        f"Save the same answer translated into English - same meaning, nothing "
        f"added or dropped - and keep speaking to the patient in their language. "
        f"Proper nouns (names, streets, medication brand names) stay as given."
    )
    return True


def _safety_reply(state: AliceState) -> str:
    """The crisis response in the conversation's language.

    A patient disclosing current risk is the one moment the intake must be
    understood. In a live Mandarin run this was the ONLY English sentence in the
    whole conversation - the crisis instruction itself - which is the worst
    possible sentence to be unreadable.

    The number stays 988 in every language: these intakes are set at
    St. Michael's Hospital, Unity Health Toronto, so that is the correct line
    whatever the patient speaks.
    """
    return safety_reply_for(
        state.get("preferred_language", "English"), SAFETY_REPLY
    )


def _safety_text_already_sent(state: AliceState) -> bool:
    """The safety message is delivered exactly once per intake.

    Tracked with its own key rather than inferred from ``safety_flag``, because
    the flag is now set before the reply is built and would otherwise suppress
    the very message it is meant to trigger.
    """
    return bool(state.get("safety_text_sent"))