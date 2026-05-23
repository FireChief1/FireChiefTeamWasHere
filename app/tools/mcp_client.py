"""MCP client: the workflow's interface to the workspace MCP server.

Workflow nodes use this client to perform file and test operations. The client
spawns the workspace MCP server as a subprocess and talks to it over stdio.
The node code is the MCP client; the LLM is never involved in tool calls.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.config import PROJECT_ROOT, settings


def _tool_text(result: object) -> str:
    """Extract the text payload from an MCP tool-call result."""
    content = getattr(result, "content", None) or []
    parts = [getattr(item, "text", "") for item in content]
    return "".join(parts)


class WorkspaceTools:
    """A typed wrapper over the workspace MCP server's tools.

    Args:
        session: An initialized MCP client session.
    """

    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def root_path(self) -> str:
        """Return the effective MCP workspace root for this session."""
        result = await self._session.call_tool("root_path", {})
        return _tool_text(result)

    async def write_file(self, rel_path: str, content: str) -> str:
        """Write a file inside the workspace via the MCP server."""
        result = await self._session.call_tool(
            "write_file", {"rel_path": rel_path, "content": content}
        )
        return _tool_text(result)

    async def read_file(self, rel_path: str) -> str:
        """Read a file from inside the workspace via the MCP server."""
        result = await self._session.call_tool(
            "read_file", {"rel_path": rel_path}
        )
        return _tool_text(result)

    async def file_exists(self, rel_path: str) -> bool:
        """Return whether a path exists inside the workspace."""
        result = await self._session.call_tool("file_exists", {"rel_path": rel_path})
        structured = getattr(result, "structuredContent", None)
        if isinstance(structured, bool):
            return structured
        if isinstance(structured, dict) and isinstance(structured.get("result"), bool):
            return cast(bool, structured["result"])
        return _tool_text(result).strip().casefold() in {"true", "1", "yes"}

    async def list_files(self, max_files: int = 200) -> list[str]:
        """List files inside the MCP root."""
        result = await self._session.call_tool("list_files", {"max_files": max_files})
        return cast(list[str], json.loads(_tool_text(result)))

    async def search_text(
        self, pattern: str, max_matches: int = 50
    ) -> list[dict[str, object]]:
        """Search text files inside the MCP root."""
        result = await self._session.call_tool(
            "search_text", {"pattern": pattern, "max_matches": max_matches}
        )
        return cast(list[dict[str, object]], json.loads(_tool_text(result)))

    async def git_status(self) -> str:
        """Return git status for the MCP root."""
        result = await self._session.call_tool("git_status", {})
        return _tool_text(result)

    async def git_diff(self, max_chars: int = 6000) -> str:
        """Return a bounded git diff summary for the MCP root."""
        result = await self._session.call_tool("git_diff", {"max_chars": max_chars})
        return _tool_text(result)

    async def run_pytest(self, rel_dir: str, timeout: int = 30) -> str:
        """Run pytest in a workspace directory via the MCP server."""
        result = await self._session.call_tool(
            "run_pytest", {"rel_dir": rel_dir, "timeout": timeout}
        )
        return _tool_text(result)

    async def git_commit(
        self, rel_dir: str, message: str, branch: str
    ) -> dict[str, object]:
        """Commit a workspace directory on a feature branch via the MCP server."""
        result = await self._session.call_tool(
            "git_commit",
            {"rel_dir": rel_dir, "message": message, "branch": branch},
        )
        return cast(dict[str, object], json.loads(_tool_text(result)))


@asynccontextmanager
async def _tools_for_root(root: Path | str) -> AsyncIterator[WorkspaceTools]:
    """Open a session to the workspace MCP server for a configured root.

    Yields:
        A WorkspaceTools wrapper bound to a live MCP session.
    """
    resolved_root = Path(root).expanduser().resolve()
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_servers.workspace_server"],
        env={
            **os.environ,
            "MCP_WORKSPACE_ROOT": str(resolved_root),
        },
        cwd=str(PROJECT_ROOT),
    )
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield WorkspaceTools(session)


@asynccontextmanager
async def workspace_tools() -> AsyncIterator[WorkspaceTools]:
    """Open a session scoped to the generated-code workspace directory."""
    async with _tools_for_root(settings.workspace_dir) as tools:
        yield tools


@asynccontextmanager
async def project_tools(root: Path | str | None = None) -> AsyncIterator[WorkspaceTools]:
    """Open a session scoped to a project folder."""
    async with _tools_for_root(root or PROJECT_ROOT) as tools:
        yield tools
