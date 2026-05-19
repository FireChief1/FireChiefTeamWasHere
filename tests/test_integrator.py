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
