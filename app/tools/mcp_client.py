"""MCP client: the workflow's interface to the workspace MCP server.

Workflow nodes use this client to perform file and test operations. The client
spawns the workspace MCP server as a subprocess and talks to it over stdio.
The node code is the MCP client; the LLM is never involved in tool calls.
"""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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

    async def run_pytest(self, rel_dir: str, timeout: int = 30) -> str:
        """Run pytest in a workspace directory via the MCP server."""
        result = await self._session.call_tool(
            "run_pytest", {"rel_dir": rel_dir, "timeout": timeout}
        )
        return _tool_text(result)

    async def git_commit(self, rel_dir: str, message: str, branch: str) -> str:
        """Commit a workspace directory on a feature branch via the MCP server."""
        result = await self._session.call_tool(
            "git_commit",
            {"rel_dir": rel_dir, "message": message, "branch": branch},
        )
        return _tool_text(result)


@asynccontextmanager
async def workspace_tools() -> AsyncIterator[WorkspaceTools]:
    """Open a session to the workspace MCP server.

    Yields:
        A WorkspaceTools wrapper bound to a live MCP session.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_servers.workspace_server"],
        env={
            **os.environ,
            "MCP_WORKSPACE_ROOT": str(settings.workspace_dir),
        },
        cwd=str(PROJECT_ROOT),
    )
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield WorkspaceTools(session)
