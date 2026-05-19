"""Workflow-level regression tests for failure handling.

These tests monkeypatch the LLM agents and MCP tools so the compiled LangGraph
workflow can be exercised without calling Ollama or touching the real
workspace.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import app.graph.nodes as graph_nodes
from app.agents.analyst import PlanOutput
from app.agents.developer import CodeFile, CodeOutput
from app.agents.qa import QAOutput
from app.agents.reviewer import ReviewOutput
from app.graph.state import AgentState
from app.graph.workflow import build_workflow


def _initial_state(*, max_iterations: int = 1) -> AgentState:
    """Build a minimal workflow state for deterministic tests."""
    return {
        "task": "Write a small add function.",
        "task_id": "pytest",
        "mode": "generate",
        "iteration": 0,
        "status": "RUNNING",
        "max_iterations": max_iterations,
        "use_rag": False,
    }


def _patch_common_agents(monkeypatch: Any) -> None:
    """Patch Analyst and Reviewer with stable successful outputs."""

    async def analyst_run(self: object, state: AgentState) -> PlanOutput:
        return PlanOutput(steps=["Implement the requested behavior."])

    async def reviewer_run(self: object, state: AgentState) -> ReviewOutput:
        return ReviewOutput(findings=[])

    monkeypatch.setattr(graph_nodes, "get_pool", lambda: object())
    monkeypatch.setattr(graph_nodes.AnalystAgent, "run", analyst_run)
    monkeypatch.setattr(graph_nodes.ReviewerAgent, "run", reviewer_run)


def _patch_valid_developer(monkeypatch: Any) -> None:
    """Patch Developer to return one valid Python module."""

    async def developer_run(self: object, state: AgentState) -> CodeOutput:
        return CodeOutput(
            approach="Return the sum directly.",
            assumptions=[],
            files=[
                CodeFile(
                    filename="adder.py",
                    content="def add(a: int, b: int) -> int:\n    return a + b\n",
                )
            ],
            summary="Built an add function.",
        )

    monkeypatch.setattr(graph_nodes.DeveloperAgent, "run", developer_run)


def _patch_qa(monkeypatch: Any, *, test_code: str) -> None:
    """Patch QA to return a deterministic test module."""

    async def qa_run(self: object, state: AgentState) -> QAOutput:
        return QAOutput(
            test_filename="test_adder.py",
            test_cases=["Checks addition."],
            test_code=test_code,
            summary="Covers addition.",
        )

    monkeypatch.setattr(graph_nodes.QAAgent, "run", qa_run)


def _patch_workspace_pytest(monkeypatch: Any, output: str) -> None:
    """Patch workspace tools so pytest returns the requested output."""

    class FakeTools:
        async def write_file(self, rel_path: str, content: str) -> str:
            return f"wrote {len(content)} chars to {rel_path}"

        async def run_pytest(self, rel_dir: str, timeout: int = 30) -> str:
            return output

    @asynccontextmanager
    async def fake_workspace_tools() -> AsyncIterator[FakeTools]:
        yield FakeTools()

    monkeypatch.setattr(graph_nodes, "workspace_tools", fake_workspace_tools)


async def test_workflow_fails_when_developer_returns_no_files(monkeypatch):
    _patch_common_agents(monkeypatch)

    async def developer_run(self: object, state: AgentState) -> CodeOutput:
        return CodeOutput(
            approach="I could not produce code.",
            assumptions=[],
            files=[],
            summary="No files.",
        )

    monkeypatch.setattr(graph_nodes.DeveloperAgent, "run", developer_run)

    result = await build_workflow().ainvoke(
        _initial_state(), config={"recursion_limit": 20}
    )

    assert result["status"] == "FAILED"
    assert result["should_abort"] is True
    assert "no source files" in result["node_error"]


async def test_workflow_fails_when_qa_returns_invalid_test_code(monkeypatch):
    _patch_common_agents(monkeypatch)
    _patch_valid_developer(monkeypatch)
    _patch_qa(monkeypatch, test_code="def test_broken(:\n")

    result = await build_workflow().ainvoke(
        _initial_state(), config={"recursion_limit": 20}
    )

    assert result["status"] == "FAILED"
    assert result["should_abort"] is True
    assert "QA test generation failed" in result["node_error"]


async def test_workflow_fails_when_pytest_runs_no_tests(monkeypatch):
    _patch_common_agents(monkeypatch)
    _patch_valid_developer(monkeypatch)
    _patch_qa(monkeypatch, test_code="def helper_only():\n    return None\n")
    _patch_workspace_pytest(monkeypatch, "no tests ran in 0.01s")

    result = await build_workflow().ainvoke(
        _initial_state(max_iterations=1), config={"recursion_limit": 20}
    )

    assert result["status"] == "FAILED"
    assert result["test_results"].failed == 1
    assert any(item.severity == "BLOCKER" for item in result["review_feedback"])
