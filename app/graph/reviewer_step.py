"""Reviewer routing node."""

from __future__ import annotations

from typing import Any

from app.agents.docs_advisor import DocsAdvisorReviewerAgent
from app.agents.project_advisor import ProjectAdvisorReviewerAgent
from app.agents.reviewer import ReviewerAgent
from app.agents.static_web_reviewer import StaticWebReviewerAgent
from app.graph.error_boundary import node_error_boundary
from app.graph.state import AgentState
from app.llm.pool import get_pool


@node_error_boundary
async def reviewer_node(state: AgentState) -> dict[str, Any]:
    """Run the Reviewer to inspect the current code."""
    agent = (
        StaticWebReviewerAgent(get_pool())
        if state.get("task_profile") == "static_web"
        else DocsAdvisorReviewerAgent(get_pool())
        if state.get("task_profile") == "docs"
        else ProjectAdvisorReviewerAgent(get_pool())
        if state.get("task_profile") == "project"
        else ReviewerAgent(get_pool())
    )
    result = await agent.run(state)
    return {"review_feedback": result.findings}
