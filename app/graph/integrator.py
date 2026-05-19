"""The Integrator node.

The Integrator is deterministic. It runs only after a SUCCESS result. It
writes the final code and commits it on a local feature branch -- all through
the workspace MCP server. It never pushes to a remote; pushing is a
human-gated action performed from the UI.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.graph.error_boundary import node_error_boundary
from app.graph.state import AgentState
from app.tools.mcp_client import workspace_tools


@node_error_boundary
async def integrator_node(state: AgentState) -> dict[str, Any]:
    """Write the final code and commit it on a local feature branch via MCP."""
    task_rel = f"task-{state['task_id']}"
    branch = f"feat/{task_rel}"
    code = state.get("code") or {}
    subject = state["task"].strip().splitlines()[0][:60]

    async with workspace_tools() as tools:
        for filename, content in code.items():
            await tools.write_file(f"{task_rel}/{filename}", content)
        result = await tools.git_commit(task_rel, f"feat: {subject}", branch)

    message = str(result.get("message") or "")
    selected_branch = str(result.get("branch") or branch)
    committed = bool(result.get("committed"))
    logger.info(f"integrator: {message}")
    return {
        "integration_message": message,
        "integration_branch": selected_branch,
        "integration_committed": committed,
    }
