"""Tests for the Node.js (node_js) profile: validation and structural QA."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import app.graph.node_qa as node_qa
from app.graph.code_validation import validate_code_files
from app.graph.node_qa import node_qa_update, run_node_qa


def _patch_node_qa(monkeypatch, *, report):
    """Patch run_node_qa's collaborators: QA agent, pool, and workspace tools."""

    class _FakeAgent:
        def __init__(self, _pool):
            pass

        async def run(self, _state):
            return SimpleNamespace(
                test_filename="generated.test.mjs",
                test_code="import test from 'node:test';\n",
                test_cases=["adds two numbers"],
            )

    class _FakeTools:
        def __init__(self):
            self.writes: list[str] = []

        async def write_file(self, rel_path, content):
            self.writes.append(rel_path)
            return "ok"

        async def run_node_tests(self, rel_dir, timeout=30):
            return report

    tools = _FakeTools()

    @asynccontextmanager
    async def fake_workspace_tools():
        yield tools

    monkeypatch.setattr(node_qa, "JavaScriptQAAgent", _FakeAgent)
    monkeypatch.setattr(node_qa, "get_pool", lambda: object())
    monkeypatch.setattr(node_qa, "workspace_tools", fake_workspace_tools)
    return tools


def test_node_validation_accepts_multi_file_js():
    error = validate_code_files(
        {
            "stack.js": "export class Stack {}\n",
            "package.json": '{"type":"module"}\n',
        },
        profile="node_js",
    )
    assert error is None


def test_node_validation_requires_at_least_one_script():
    error = validate_code_files({"package.json": "{}\n"}, profile="node_js")
    assert error is not None
    assert "at least one JavaScript" in error


def test_node_validation_rejects_unsupported_suffix():
    error = validate_code_files({"main.py": "print(1)\n"}, profile="node_js")
    assert error is not None
    assert "unsupported filename" in error


def test_node_qa_passes_for_exported_balanced_module():
    update = node_qa_update(
        {"code": {"adder.js": "export function add(a, b) { return a + b; }\n"}}
    )
    assert update["test_results"].failed == 0
    assert update["test_results"].passed > 0
    assert "review_feedback" not in update


def test_node_qa_flags_missing_export_and_unbalanced_braces():
    update = node_qa_update(
        {"code": {"broken.js": "function add(a, b) { return a + b;\n"}}
    )
    results = update["test_results"]
    assert results.failed > 0
    # A failure folds into review feedback as a BLOCKER for the fix loop.
    feedback = update["review_feedback"]
    assert any(item.severity == "BLOCKER" for item in feedback)


async def test_run_node_qa_uses_real_results_when_node_available(monkeypatch):
    _patch_node_qa(
        monkeypatch,
        report={"available": True, "passed": 3, "failed": 0, "total": 3, "output": "# pass 3"},
    )
    update = await run_node_qa(
        {"task": "add", "task_id": "t1", "code": {"adder.js": "export function add(a,b){return a+b;}"}}
    )
    assert update["test_results"].passed == 3
    assert update["test_results"].failed == 0
    assert "review_feedback" not in update


async def test_run_node_qa_folds_failures_into_blocker_feedback(monkeypatch):
    _patch_node_qa(
        monkeypatch,
        report={"available": True, "passed": 1, "failed": 2, "total": 3, "output": "# fail 2"},
    )
    update = await run_node_qa(
        {"task": "add", "task_id": "t1", "code": {"adder.js": "export function add(a,b){return a+b;}"}}
    )
    assert update["test_results"].failed == 2
    assert any(item.severity == "BLOCKER" for item in update["review_feedback"])


async def test_run_node_qa_falls_back_to_structural_when_node_unavailable(monkeypatch):
    _patch_node_qa(
        monkeypatch,
        report={"available": False, "passed": 0, "failed": 0, "total": 0, "output": "node missing"},
    )
    update = await run_node_qa(
        {"task": "add", "task_id": "t1", "code": {"adder.js": "export function add(a,b){return a+b;}"}}
    )
    # Structural fallback ran: it reports its own deterministic checks.
    assert update["test_code"] == "Node.js structural validation ran without execution."
    assert update["test_results"].total > 0
