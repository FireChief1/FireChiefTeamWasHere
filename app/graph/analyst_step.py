"""Analyst planning node."""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.agents.analyst import AnalystAgent
from app.graph.error_boundary import node_error_boundary
from app.graph.state import AgentState
from app.llm.pool import get_pool

_ANALYST_FALLBACK_PLAN = ["Implement directly from the task description."]


@node_error_boundary
async def analyst_node(state: AgentState) -> dict[str, Any]:
    """Run the Analyst to produce an implementation plan."""
    agent = AnalystAgent(get_pool())
    result = await agent.run(state)
    plan = _clean_plan(result.steps)
    if not plan:
        logger.warning("Analyst produced an empty plan; retrying once")
        result = await agent.run(state)
        plan = _clean_plan(result.steps)
    if not plan:
        logger.warning("Analyst plan fallback activated")
        plan = list(_ANALYST_FALLBACK_PLAN)
    return {"plan": plan}


def _clean_plan(steps: list[str]) -> list[str]:
    """Remove blank plan steps while preserving order."""
    return [step.strip() for step in steps if step.strip()]
