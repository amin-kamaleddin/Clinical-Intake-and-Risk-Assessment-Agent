import copy

from core.state import AliceState, initial_state
from graph.builder import graph
from ui.display import format_display


def get_fresh_state() -> AliceState:
    """Return a deep copy of initial_state so each session is fully independent."""
    return copy.deepcopy(initial_state)


def start() -> tuple[list[dict], AliceState, str]:
    """
    Called once on page load.
    Returns the welcome message, a blank state, and the empty info panel.
    """
    state = get_fresh_state()
    welcome = [{"role": "assistant", "content": "👋 Welcome! Please select a section above to begin your intake."}]
    return welcome, state, format_display(state)


def chat(message: str, history: list[dict], alice_state: AliceState) -> tuple[list[dict], AliceState, str]:
    """
    Called on every user message submission.
    Appends the user message to state, runs the graph, then updates history.
    """
    if alice_state is None:
        _, alice_state, _ = start()

    # Guard: do nothing if no section selected or message is blank
    if alice_state["current_section"] is None or not message.strip():
        return history, alice_state, format_display(alice_state)

    alice_state["messages"] = alice_state["messages"] + [{"role": "user", "content": message}]
    alice_state = graph.invoke(alice_state)

    reply   = alice_state["messages"][-1]["content"]
    history = history + [
        {"role": "user",      "content": message},
        {"role": "assistant", "content": reply},
    ]
    return history, alice_state, format_display(alice_state)


def switch_section(section: str, alice_state: AliceState) -> tuple[list[dict], AliceState, str]:
    """
    Called when the user clicks a section button.
    Resets the message history for the new section and gets ALICE's opening line.
    """
    if alice_state is None:
        _, alice_state, _ = start()

    alice_state["current_section"] = section
    alice_state["messages"]        = []
    alice_state = graph.invoke(alice_state)

    reply   = alice_state["messages"][-1]["content"]
    history = [{"role": "assistant", "content": reply}]
    return history, alice_state, format_display(alice_state)
