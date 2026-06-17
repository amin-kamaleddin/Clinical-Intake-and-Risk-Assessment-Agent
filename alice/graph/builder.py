from langgraph.graph import StateGraph, END

from core.state import AliceState
from graph.nodes import section_node


# ── Graph definition ───────────────────────────────────────────────────────────
# Currently a single node. Adding nodes here (e.g. a router, a summary node)
# is the only change needed to extend the graph topology.

def build_graph():
    builder = StateGraph(AliceState)
    builder.add_node("section", section_node)
    builder.set_entry_point("section")
    builder.add_edge("section", END)
    return builder.compile()


# ── Compiled graph — import this everywhere ────────────────────────────────────
graph = build_graph()
