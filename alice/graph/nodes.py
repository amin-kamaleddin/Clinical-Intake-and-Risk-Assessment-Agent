from langchain_openai import ChatOpenAI

from core.state import AliceState
from core.tools import tools
from core.validators import FIELD_VALIDATORS
from core.storage import save_record
from prompts.builder import build_system_prompt, get_pending_fields


# ── Hardcoded safety response ──────────────────────────────────────────────────
# Displayed immediately after raise_safety_flag fires.
# The LLM never generates this — it is always exactly this text.

SAFETY_RESPONSE = (
    "I'm really glad you shared that with me. "
    "You are not alone. Please call 988 or go to your nearest emergency room. "
    "A member of our care team has been notified. "
    "Whenever you're ready, we can continue with the intake."
)


def section_node(state: AliceState) -> AliceState:
    """
    Single LangGraph node — handles one full conversational turn:

    1. Call the model (with tools bound) on the current message history.
    2. Process any tool calls:
         - save_answer  → validate + write to state
         - raise_safety_flag → set safety_flag, sanitise history, emit hardcoded reply
    3. If tools fired (and no safety flag), call the model a second time
       so it can generate the next question with updated state context.
    4. Append the final assistant reply to state["messages"].
    5. Check whether the section is now complete.
    """
    section = state["current_section"]
    model   = ChatOpenAI(model="gpt-5.4-mini").bind_tools(tools)
    llm     = ChatOpenAI(model="gpt-5.4-mini")

    system  = {"role": "system", "content": build_system_prompt(state)}

    # ── Call 1: let the model fire tool calls ──────────────────────────────────
    response = model.invoke([system] + state["messages"])

    safety_raised = False
    tool_results  = {}

    for tc in response.tool_calls:
        if tc["name"] == "save_answer":
            field     = tc["args"]["field_name"]
            value     = tc["args"]["value"]
            validator = FIELD_VALIDATORS.get(field)

            if validator:
                valid, result = validator(value)
                if valid:
                    state[section][field]  = result
                    tool_results[tc["id"]] = "saved"
                else:
                    # Return the error message so the model can relay it
                    tool_results[tc["id"]] = f"invalid: {result}"
            else:
                # No validator for this field — save as-is
                state[section][field]      = value
                tool_results[tc["id"]]     = "saved"

        elif tc["name"] == "raise_safety_flag":
            state["safety_flag"]           = True
            safety_raised                  = True
            tool_results[tc["id"]]         = "flag_raised"

    # ── Build reply — three possible situations ────────────────────────────────

    if safety_raised:
        # Sanitise the triggering message so future context stays clean,
        # then emit the hardcoded crisis response — no second LLM call.
        state["messages"][-1] = {"role": "user", "content": "safety flag was raised and handled."}
        reply         = SAFETY_RESPONSE
        tool_exchange = []

    elif not response.tool_calls:
        # No tools fired at all — Call 1 reply is already the final reply.
        reply         = response.content
        tool_exchange = []

    else:
        # Tools fired successfully — Call 2 generates the next question
        # using the now-updated state (fresh system prompt).
        tool_exchange = [response] + [
            {
                "role":         "tool",
                "content":      tool_results[tc["id"]],
                "tool_call_id": tc["id"],
            }
            for tc in response.tool_calls
        ]
        updated_system = {"role": "system", "content": build_system_prompt(state)}
        reply = llm.invoke([updated_system] + state["messages"] + tool_exchange).content

    # ── Check section completion ───────────────────────────────────────────────
    pending = get_pending_fields(state, section)
    if not pending and section not in state["sections_completed"]:
        state["sections_completed"].append(section)

    # ── Auto-save when both sections are complete ──────────────────────────────
    if set(state["sections_completed"]) == {"general_information", "current_concerns"}:
        save_record(state)

    # ── Persist messages ───────────────────────────────────────────────────────
    state["messages"]             = state["messages"] + tool_exchange + [{"role": "assistant", "content": reply}]
    state["conversation_started"] = True

    return state
