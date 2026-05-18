"""The Supervisor node and its routing function.

The Supervisor is deterministic -- it makes no LLM call. It inspects the
Reviewer's findings (test failures are already folded in as BLOCKER findings
by the QA node), decides whether the code needs another Developer iteration,
sets the workflow status, tracks the best code version, and detects an
oscillating loop.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.config import settings
from app.graph.error_boundary import node_error_boundary
from app.graph.state import AgentState


@node_error_boundary
async def supervisor_node(state: AgentState) -> dict[str, Any]:
    """Decide whether to loop back to the Developer or finish the workflow."""
    feedback = state.get("review_feedback") or []
    iteration = state.get("iteration", 0)
    prior_history = state.get("issue_count_history") or []

    issue_count = len(feedback)
    history = prior_history + [issue_count]
    has_blocker = any(f.severity == "BLOCKER" for f in feedback)

    update: dict[str, Any] = {"issue_count_history": history}

    # Keep the lowest-issue code version seen so far.
    prior_best = min(prior_history) if prior_history else None
    if prior_best is None or issue_count <= prior_best:
        update["best_code"] = dict(state.get("code") or {})

    # Clean code -> success.
    if issue_count == 0:
        update["status"] = "SUCCESS"
        logger.info("supervisor: code is clean -> SUCCESS")
        return update

    max_iterations = state.get("max_iterations") or settings.max_iterations
    at_max = (iteration + 1) >= max_iterations
    no_progress = len(history) >= 2 and history[-1] >= history[-2]

    if at_max or no_progress:
        update["status"] = "FAILED" if has_blocker else "COMPLETED_WITH_WARNINGS"
        update["code"] = update.get("best_code") or dict(state.get("code") or {})
        reason = "max iterations reached" if at_max else "no progress"
        logger.info(f"supervisor: stopping ({reason}) -> {update['status']}")
        return update

    # Loop back to the Developer for another iteration.
    update["status"] = "RUNNING"
    update["iteration"] = iteration + 1
    logger.info(
        f"supervisor: {issue_count} issue(s) -> loop (iteration {iteration + 1})"
    )
    return update


def route_after_supervisor(state: AgentState) -> str:
    """Route from the Supervisor: loop back, integrate, or end.

    Args:
        state: The workflow state after the Supervisor node has run.

    Returns:
        One of ``"developer"``, ``"integrator"``, or ``"end"``.
    """
    if state.get("should_abort"):
        return "end"
    status = state.get("status")
    if status == "SUCCESS":
        return "integrator"
    if status == "RUNNING":
        return "developer"
    return "end"
