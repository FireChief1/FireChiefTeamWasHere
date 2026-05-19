"""The Supervisor node and its routing function.

The Supervisor is deterministic -- it makes no LLM call. It inspects the
Reviewer's findings (test failures are folded in as BLOCKER findings by the QA
node), decides whether the code needs another Developer iteration, sets the
workflow status, tracks the best code version, and detects an oscillating loop.

Only BLOCKER and MAJOR findings trigger another iteration. MINOR findings are
cosmetic; looping to fix them risks breaking working code, so they are left as
warnings instead.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.config import settings
from app.graph.error_boundary import node_error_boundary
from app.graph.state import AgentState

_BLOCKING = ("BLOCKER", "MAJOR")


@node_error_boundary
async def supervisor_node(state: AgentState) -> dict[str, Any]:
    """Decide whether to loop back to the Developer or finish the workflow."""
    feedback = state.get("review_feedback") or []
    iteration = state.get("iteration", 0)
    prior_history = state.get("issue_count_history") or []

    # Only BLOCKER and MAJOR findings are worth another iteration.
    blocking = [f for f in feedback if f.severity in _BLOCKING]
    has_blocker = any(f.severity == "BLOCKER" for f in feedback)
    issue_count = len(blocking)
    history = prior_history + [issue_count]

    update: dict[str, Any] = {"issue_count_history": history}

    # Keep the version with the fewest blocking issues seen so far.
    prior_best = min(prior_history) if prior_history else None
    if prior_best is None or issue_count <= prior_best:
        update["best_code"] = dict(state.get("code") or {})

    # No blocking issues -> the code is good enough; finish without looping.
    if issue_count == 0:
        update["status"] = "COMPLETED_WITH_WARNINGS" if feedback else "SUCCESS"
        logger.info(f"supervisor: no blocking issues -> {update['status']}")
        return update

    max_iterations = state.get("max_iterations") or settings.max_iterations
    at_max = (iteration + 1) >= max_iterations
    no_progress = len(history) >= 2 and history[-1] >= history[-2]

    if at_max or no_progress:
        update["status"] = "FAILED" if has_blocker else "COMPLETED_WITH_WARNINGS"
        update["code"] = (
            update.get("best_code")
            or dict(state.get("best_code") or {})
            or dict(state.get("code") or {})
        )
        reason = "max iterations reached" if at_max else "no progress"
        logger.info(f"supervisor: stopping ({reason}) -> {update['status']}")
        return update

    # Loop back to the Developer for another iteration.
    update["status"] = "RUNNING"
    update["iteration"] = iteration + 1
    logger.info(
        f"supervisor: {issue_count} blocking issue(s) -> "
        f"loop (iteration {iteration + 1})"
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
    if status in ("SUCCESS", "COMPLETED_WITH_WARNINGS"):
        return "integrator"
    if status == "RUNNING":
        return "developer"
    return "end"
