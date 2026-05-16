"""The LangGraph workflow that orchestrates the agent team.

The workflow wires the agent nodes into a state machine: the Analyst plans,
the Developer writes code, the Reviewer and QA inspect it, and the Supervisor
decides whether to loop back for fixes or finish. On success the Integrator
commits the result.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph

from app.graph.integrator import integrator_node
from app.graph.nodes import (
    analyst_node,
    developer_node,
    qa_node,
    rag_node,
    reviewer_node,
)
from app.graph.state import AgentState
from app.graph.supervisor import route_after_supervisor, supervisor_node

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph


def build_workflow() -> CompiledStateGraph:
    """Build and compile the multi-agent workflow graph.

    The graph runs Analyst -> Developer -> Reviewer -> QA -> Supervisor. The
    Supervisor either loops back to the Developer, routes to the Integrator on
    success, or ends the workflow.

    Returns:
        The compiled LangGraph workflow, ready for ``ainvoke``.
    """
    graph = StateGraph(AgentState)

    # The add_node calls are suppressed below: the node functions are valid
    # LangGraph nodes at runtime but do not match LangGraph's typed overloads.
    graph.add_node("rag", rag_node)  # type: ignore[call-overload]
    graph.add_node("analyst", analyst_node)  # type: ignore[call-overload]
    graph.add_node("developer", developer_node)  # type: ignore[call-overload]
    graph.add_node("reviewer", reviewer_node)  # type: ignore[call-overload]
    graph.add_node("qa", qa_node)  # type: ignore[call-overload]
    graph.add_node("supervisor", supervisor_node)  # type: ignore[call-overload]
    graph.add_node("integrator", integrator_node)  # type: ignore[call-overload]

    graph.add_edge(START, "rag")
    graph.add_edge("rag", "analyst")
    graph.add_edge("analyst", "developer")
    graph.add_edge("developer", "reviewer")
    graph.add_edge("reviewer", "qa")
    graph.add_edge("qa", "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {"developer": "developer", "integrator": "integrator", "end": END},
    )
    graph.add_edge("integrator", END)

    return graph.compile()
