from langchain_openai import ChatOpenAI

from core.config import MODEL_NAME
from core.state import AliceState
from core.tools import tools
from core.validators import FIELD_VALIDATORS
from core.safety import explicit_safety_trigger, SAFETY_REPLY
from core.scoring import calculate_phq9_total, calculate_gad7_total
from core.storage import save_record
from prompts.builder import build_system_prompt, get_pending_fields


model = ChatOpenAI(model=MODEL_NAME).bind_tools(tools)
llm   = ChatOpenAI(model=MODEL_NAME)


def handle_safety(state: AliceState) -> AliceState:
    """Raise the safety flag once while preserving the original conversation."""
    already_raised = bool(state.get("safety_flag"))
    state["safety_flag"] = True

    # Do not overwrite the patient's original message.
    # Add the safety reply only the first time the flag is raised.
    if not already_raised:
        state["messages"] = state["messages"] + [
            {"role": "assistant", "content": SAFETY_REPLY}
        ]

    state["conversation_started"] = True
    save_record(state)
    return state


def apply_tool_calls(state: AliceState, section: str, response):
    """Process save_answer / raise_safety_flag calls. Returns (tool_results, safety_raised)."""
    tool_results  = {}
    safety_raised = False

    for tc in response.tool_calls:
        if tc["name"] == "save_answer":
            field     = tc["args"]["field_name"]
            value     = tc["args"]["value"]
            validator = FIELD_VALIDATORS.get(field)

            saved_value = None
            if validator:
                valid, result = validator(value)
                if valid:
                    state[section][field] = result
                    saved_value = result
                    tool_results[tc["id"]] = "saved"
                else:
                    tool_results[tc["id"]] = f"invalid: {result}"
            else:
                state[section][field] = value
                saved_value = value
                tool_results[tc["id"]] = "saved"

            # PHQ-9 question 9 is a deterministic safety rule.
            # Any successfully saved score above zero raises the flag, even when
            # the patient's raw reply is only "Several days".
            if section == "phq9" and field == "phq9_q9" and saved_value is not None:
                try:
                    q9_score = int(saved_value)
                except (TypeError, ValueError):
                    q9_score = 0

                if q9_score > 0 and not state.get("safety_flag", False):
                    safety_raised = True

        elif tc["name"] == "raise_safety_flag":
            # Defer the actual state mutation to handle_safety(), which also
            # appends the safety reply exactly once and saves the record.
            if not state.get("safety_flag", False):
                safety_raised = True
                tool_results[tc["id"]] = "flag_raised"
            else:
                tool_results[tc["id"]] = "flag_already_raised"

    return tool_results, safety_raised


def update_completion(state: AliceState, section: str):
    """Add/remove the section from completed based on pending fields, then save if all done."""
    pending = get_pending_fields(state, section)

    if pending:
        if section in state["sections_completed"]:
            state["sections_completed"].remove(section)
    elif section not in state["sections_completed"]:
        state["sections_completed"].append(section)


def section_node(state: AliceState) -> AliceState:
    section = state["current_section"]

    # ── Stage 1: deterministic safety gate on raw patient text ──
    # Run only before a safety concern has already been handled.
    # IMPORTANT: explicit_safety_trigger() must distinguish current patient risk
    # from historical, negated, hypothetical, and third-person statements.
    if (
        not state.get("safety_flag", False)
        and state["messages"]
        and state["messages"][-1].get("role") == "user"
    ):
        if explicit_safety_trigger(state["messages"][-1]["content"]):
            return handle_safety(state)

    # ── Stage 2: call the model ──
    system   = {"role": "system", "content": build_system_prompt(state)}
    response = model.invoke([system] + state["messages"])

    # ── Stage 3: process tool calls ──
    tool_results, safety_raised = apply_tool_calls(state, section, response)

    # ── Stage 4: section-specific scoring ──
    if section == "phq9":
        state["phq9"]["phq9_total"] = calculate_phq9_total(state)
    if section == "gad7":
        state["gad7"]["gad7_total"] = calculate_gad7_total(state)

    # ── Stage 5: build the reply ──
    if safety_raised:
        return handle_safety(state)

    if not response.tool_calls:
        reply         = response.content
        tool_exchange = []
    else:
        tool_exchange  = [response] + [
            {"role": "tool", "content": tool_results[tc["id"]], "tool_call_id": tc["id"]}
            for tc in response.tool_calls
        ]
        updated_system = {"role": "system", "content": build_system_prompt(state)}
        reply          = llm.invoke([updated_system] + state["messages"] + tool_exchange).content

    # ── Stage 6: completion check + save after every field ──
    update_completion(state, section)
    save_record(state)

    # ── Stage 7: commit messages ──
    state["messages"]             = state["messages"] + tool_exchange + [{"role": "assistant", "content": reply}]
    state["conversation_started"] = True
    return state
