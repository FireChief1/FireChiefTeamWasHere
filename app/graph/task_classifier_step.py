"""Task profile selection node."""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.graph.error_boundary import node_error_boundary
from app.graph.state import AgentState
from app.graph.task_profile import classify_task_profile


@node_error_boundary
async def task_classifier_node(state: AgentState) -> dict[str, Any]:
    """Select the implementation profile used by downstream nodes."""
    profile, reason = classify_task_profile(state)
    logger.info(f"task profile: {profile} ({reason})")
    return {"task_profile": profile, "task_profile_reason": reason}
