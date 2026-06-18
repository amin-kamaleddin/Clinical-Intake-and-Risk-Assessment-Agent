from langgraph.graph import StateGraph, END

from core.state import AliceState
from graph.nodes import section_node


def build_graph():
    builder = StateGraph(AliceState)
    builder.add_node("section", section_node)
    builder.set_entry_point("section")
    builder.add_edge("section", END)
    return builder.compile()


graph = build_graph()
