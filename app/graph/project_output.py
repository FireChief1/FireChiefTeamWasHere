"""Project Mode diff preview and apply helpers."""

from __future__ import annotations

import difflib
from typing import Any

from app.tools.mcp_client import project_tools


async def preview_project_files(
    target_path: str, code: dict[str, str]
) -> dict[str, Any]:
    """Build a unified diff preview for generated project files."""
    file_actions: list[dict[str, str]] = []
    diff_parts: list[str] = []

    async with project_tools(target_path) as tools:
        mcp_root = await tools.root_path()
        for filename, content in code.items():
            exists = await tools.file_exists(filename)
            before = await tools.read_file(filename) if exists else None
            action = _file_action(before, content)
            file_actions.append({"file": filename, "action": action})
            if action == "unchanged":
                continue
            diff = unified_file_diff(filename, before, content)
            if diff:
                diff_parts.append(diff)

    return {
        "integration_target_path": str(target_path),
        "project_mcp_root": mcp_root,
        "integration_planned_files": list(code),
        "integration_file_actions": file_actions,
        "integration_diff": "\n".join(diff_parts),
        "integration_preview_only": True,
    }


async def apply_project_files(target_path: str, code: dict[str, str]) -> dict[str, Any]:
    """Write generated files into the selected project folder."""
    written_files: list[str] = []
    async with project_tools(target_path) as tools:
        mcp_root = await tools.root_path()
        for filename, content in code.items():
            await tools.write_file(filename, content)
            written_files.append(filename)

    return {
        "integration_target_path": str(target_path),
        "project_mcp_root": mcp_root,
        "integration_written_files": written_files,
        "integration_preview_only": False,
    }


def unified_file_diff(filename: str, before: str | None, after: str) -> str:
    """Return a unified diff for a generated file."""
    before_lines = [] if before is None else before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    fromfile = "/dev/null" if before is None else filename
    lines = difflib.unified_diff(
        before_lines,
        after_lines,
        fromfile=fromfile,
        tofile=filename,
        lineterm="",
    )
    return "\n".join(lines)


def _file_action(before: str | None, after: str) -> str:
    """Return the preview action for one generated file."""
    if before is None:
        return "create"
    if before == after:
        return "unchanged"
    return "modify"
