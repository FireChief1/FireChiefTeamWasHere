"""Tests for the deterministic Integrator node."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import app.graph.integrator as integrator
from app.graph.state import AgentState


async def test_integrator_returns_git_commit_metadata(monkeypatch):
    writes: list[tuple[str, str]] = []

    class FakeTools:
        async def write_file(self, rel_path: str, content: str) -> str:
            writes.append((rel_path, content))
            return f"wrote {rel_path}"

        async def git_commit(
            self, rel_dir: str, message: str, branch: str
        ) -> dict[str, object]:
            return {
                "committed": True,
                "branch": "feat/task-pytest-2",
                "message": f"committed on feat/task-pytest-2: {message}",
            }

    @asynccontextmanager
    async def fake_workspace_tools() -> AsyncIterator[FakeTools]:
        yield FakeTools()

    monkeypatch.setattr(integrator, "workspace_tools", fake_workspace_tools)

    state: AgentState = {
        "task": "Write an add function.",
        "task_id": "pytest",
        "code": {"adder.py": "def add(a, b):\n    return a + b\n"},
    }

    update = await integrator.integrator_node(state)

    assert writes == [
        ("task-pytest/adder.py", "def add(a, b):\n    return a + b\n")
    ]
    assert update["integration_committed"] is True
    assert update["integration_branch"] == "feat/task-pytest-2"
    assert "committed on feat/task-pytest-2" in update["integration_message"]


async def test_integrator_previews_project_mode_files_without_writing(tmp_path):
    state: AgentState = {
        "task": "Add a helper file.",
        "task_id": "pytest",
        "mode": "project",
        "project_path": str(tmp_path),
        "code": {"helper.py": "def helper():\n    return True\n"},
    }

    update = await integrator.integrator_node(state)

    # Project Mode is preview-only: the workflow never writes into the project.
    # The actual write happens through the explicit project-apply endpoint.
    assert update["integration_target_path"] == str(tmp_path)
    assert update["integration_planned_files"] == ["helper.py"]
    assert update["integration_file_actions"] == [
        {"file": "helper.py", "action": "create"}
    ]
    assert "--- /dev/null" in update["integration_diff"]
    assert "+++ helper.py" in update["integration_diff"]
    assert update["integration_written_files"] == []
    assert update["integration_preview_only"] is True
    assert "preview only" in update["integration_message"]
