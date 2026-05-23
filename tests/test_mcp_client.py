"""Tests for the typed MCP client wrappers."""

from __future__ import annotations

from app.tools.mcp_client import project_tools


async def test_project_tools_uses_selected_root_for_reads_and_writes(tmp_path):
    async with project_tools(tmp_path) as tools:
        assert await tools.root_path() == str(tmp_path.resolve())
        assert await tools.list_files(max_files=20) == []
        assert await tools.file_exists("index.html") is False

        await tools.write_file("index.html", "<!doctype html><html></html>\n")

        assert (tmp_path / "index.html").exists()
        assert await tools.file_exists("index.html") is True
        assert await tools.list_files(max_files=20) == ["index.html"]
