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
from app.graph.project_output import preview_project_files
from app.graph.state import AgentState
from app.tools.mcp_client import project_tools, workspace_tools


@node_error_boundary
async def integrator_node(state: AgentState) -> dict[str, Any]:
    """Write the final code and commit it on a local feature branch via MCP."""
    if state.get("mode") == "project":
        return await _write_project_files(state)

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


async def _write_project_files(state: AgentState) -> dict[str, Any]:
    """Preview or write generated files into the selected project folder."""
    target_path = state.get("project_path")
    code = state.get("code") or {}
    planned_files = list(code)
    if not target_path:
        return {
            "integration_message": (
                "Project Mode target folder is missing; files were not written."
            ),
            "integration_branch": "",
            "integration_committed": False,
            "integration_target_path": "",
            "integration_planned_files": planned_files,
            "integration_file_actions": [],
            "integration_diff": "",
            "integration_written_files": [],
            "integration_preview_only": True,
        }

    if not state.get("project_apply_changes", False):
        preview = await preview_project_files(str(target_path), code)
        message = (
            f"preview only: {len(planned_files)} file(s) ready for project "
            f"folder: {target_path}"
        )
        logger.info(f"integrator: {message}")
        return {
            **preview,
            "integration_message": message,
            "integration_branch": "",
            "integration_committed": False,
            "integration_written_files": [],
            "integration_preview_only": True,
        }

    written_files: list[str] = []
    async with project_tools(target_path) as tools:
        for filename, content in code.items():
            await tools.write_file(filename, content)
            written_files.append(filename)

    message = (
        f"wrote {len(written_files)} file(s) to project folder: {target_path}"
    )
    logger.info(f"integrator: {message}")
    return {
        "integration_message": message,
        "integration_branch": "",
        "integration_committed": False,
        "integration_target_path": str(target_path),
        "integration_planned_files": planned_files,
        "integration_file_actions": [],
        "integration_diff": "",
        "integration_written_files": written_files,
        "integration_preview_only": False,
    }
