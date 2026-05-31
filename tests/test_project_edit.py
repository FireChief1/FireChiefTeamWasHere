"""Tests for existing-file editing (full-content edit targets)."""

from __future__ import annotations

from contextlib import asynccontextmanager

import app.graph.project_intake as project_intake
from app.agents.project_context import project_context_section
from app.graph.project_intake import (
    project_edit_target_files,
    task_edit_target_files,
)


def test_task_edit_targets_match_named_files_only():
    files = ["src/calculator.js", "src/util.js", "README.md"]
    # Only files explicitly named (path or basename) become edit targets.
    assert task_edit_target_files("fix the bug in calculator.js", files) == [
        "src/calculator.js"
    ]
    assert task_edit_target_files("update README.md headers", files) == ["README.md"]
    # An unrelated task names nothing -> no edit targets.
    assert task_edit_target_files("make a brand new page", files) == []


class _FakeTools:
    def __init__(self, contents):
        self._contents = contents

    async def read_file(self, rel_path):
        return self._contents[rel_path]


async def test_project_edit_target_files_reads_full_content():
    tools = _FakeTools({"app/core.js": "A" * 12000})
    targets = await project_edit_target_files(
        tools, "patch app/core.js please", ["app/core.js", "other.js"]
    )
    assert len(targets) == 1
    assert targets[0]["file"] == "app/core.js"
    # Full content (capped) is provided, marked truncated when over the cap.
    assert len(str(targets[0]["content"])) == 8000
    assert targets[0]["truncated"] is True


def test_project_context_renders_files_to_edit_section():
    section = project_context_section(
        {
            "mode": "project",
            "task_profile": "node_js",
            "project_edit_targets": [
                {"file": "adder.js", "content": "export function add(){}", "truncated": False}
            ],
        }
    )
    assert "FILES TO EDIT" in section
    assert "Return the COMPLETE updated file" in section
    assert "export function add(){}" in section


async def test_intake_collects_edit_targets_only_for_modify(monkeypatch, tmp_path):
    class FakeProjectTools:
        async def root_path(self):
            return str(tmp_path.resolve())

        async def list_files(self, max_files=200):
            return ["calculator.js", "README.md"]

        async def search_text(self, pattern, max_matches=50):
            return []

        async def read_file(self, filename):
            return f"// full content of {filename}\n" + "x" * 50

        async def git_status(self):
            return "## main...origin/main\n"

        async def git_diff(self, max_chars=6000):
            return ""

    @asynccontextmanager
    async def fake_project_tools(root):
        yield FakeProjectTools()

    monkeypatch.setattr(project_intake, "project_tools", fake_project_tools)

    base_state = {
        "task": "fix the rounding bug in calculator.js",
        "mode": "project",
        "project_path": str(tmp_path),
    }

    # modify_project -> edit targets collected with full content.
    modify = await project_intake.project_intake_node(
        {**base_state, "project_chat_action": "modify_project"}
    )
    assert [t["file"] for t in modify["project_edit_targets"]] == ["calculator.js"]

    # analyze_project -> no edit targets (precise gating).
    analyze = await project_intake.project_intake_node(
        {**base_state, "project_chat_action": "analyze_project"}
    )
    assert analyze["project_edit_targets"] == []
