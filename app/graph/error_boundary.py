"""Error boundary for LangGraph nodes.

Every workflow node is wrapped by ``node_error_boundary``. The wrapper does
two things: it skips a node when the workflow is already aborting, and it
catches any unhandled exception so a bug in one node ends the workflow cleanly
with an honest FAILED status instead of crashing the process.
"""

from __future__ import annotations

import functools
import traceback
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from app.graph.state import AgentState

NodeFunc = Callable[[AgentState], Awaitable[dict[str, Any]]]


def node_error_boundary(func: NodeFunc) -> NodeFunc:
    """Wrap a node so failures abort the workflow cleanly.

    If ``state["should_abort"]`` is already set, the node is skipped. If the
    node raises, the exception is logged and converted into a state update
    that sets ``node_error``, ``should_abort``, and a FAILED status.

    Args:
        func: The async node function to wrap.

    Returns:
        The wrapped node function.
    """

    @functools.wraps(func)
    async def wrapper(state: AgentState) -> dict[str, Any]:
        if state.get("should_abort"):
            return {}
        try:
            return await func(state)
        except Exception as exc:  # noqa: BLE001 - the boundary catches everything
            logger.error(
                f"node '{func.__name__}' failed:\n{traceback.format_exc()}"
            )
            return {
                "node_error": f"{func.__name__}: {exc}",
                "should_abort": True,
                "status": "FAILED",
            }

    return wrapper
