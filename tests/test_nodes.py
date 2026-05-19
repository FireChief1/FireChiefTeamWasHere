"""Tests for the pure helper functions used by the workflow nodes."""

from __future__ import annotations

import pytest

import app.graph.nodes as graph_nodes
from app.agents.analyst import PlanOutput
from app.graph.nodes import (
    _build_test_imports,
    _clean_plan,
    _count,
    _parse_pytest,
    _public_names,
    _strip_code_fences,
    _validate_code_files,
    analyst_node,
    rag_node,
)
from app.rag.retriever import RetrievalResult, RetrievedChunk


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("```python\ncode\n```", "code"),
        ("```\ncode\n```", "code"),
        ("plain code", "plain code"),
        ("def f():\n    pass", "def f():\n    pass"),
    ],
)
def test_strip_code_fences(raw, expected):
    assert _strip_code_fences(raw) == expected


@pytest.mark.parametrize(
    "pattern,text,expected",
    [
        (r"(\d+) passed", "5 passed", 5),
        (r"(\d+) failed", "no match here", 0),
        (r"(\d+) passed", "16 passed, 2 failed", 16),
    ],
)
def test_count(pattern, text, expected):
    assert _count(pattern, text) == expected


def test_public_names_extracts_classes_and_functions():
    code = "class Foo:\n    pass\n\n\ndef bar():\n    pass\n"
    assert _public_names(code) == ["Foo", "bar"]


def test_public_names_excludes_private_names():
    code = "def _hidden():\n    pass\n\n\ndef visible():\n    pass\n"
    assert _public_names(code) == ["visible"]


def test_public_names_returns_empty_on_a_syntax_error():
    assert _public_names("def broken(:\n") == []


def test_build_test_imports_adds_missing_imports():
    header = _build_test_imports(
        "def test_x(): pass", {"calc.py": "def add(): pass"}
    )
    assert "import pytest" in header
    assert "from calc import add" in header


def test_build_test_imports_skips_imports_already_present():
    test_code = "import pytest\nfrom calc import add\n\ndef test_x(): pass"
    header = _build_test_imports(test_code, {"calc.py": "def add(): pass"})
    assert header == ""


def test_parse_pytest_reads_pass_and_fail_counts():
    results = _parse_pytest("16 passed, 2 failed in 0.1s")
    assert results.passed == 16
    assert results.failed == 2
    assert results.total == 18


def test_parse_pytest_treats_a_timeout_as_a_failure():
    results = _parse_pytest("TIMEOUT: test execution exceeded the time limit")
    assert results.failed == 1
    assert results.passed == 0


def test_parse_pytest_treats_no_tests_as_a_failure():
    results = _parse_pytest("no tests ran in 0.01s")
    assert results.failed == 1
    assert results.passed == 0
    assert results.total == 1


def test_parse_pytest_treats_skipped_only_runs_as_a_failure():
    results = _parse_pytest("1 skipped in 0.01s")
    assert results.failed == 1
    assert results.passed == 0
    assert results.total == 1


def test_validate_code_files_accepts_a_simple_python_module():
    assert _validate_code_files({"calculator.py": "def add(a, b):\n    return a + b\n"}) is None


def test_validate_code_files_rejects_empty_output():
    assert "no source files" in (_validate_code_files({}) or "")


def test_validate_code_files_rejects_unsupported_filenames():
    error = _validate_code_files({"src/calculator.py": "def add():\n    return 1\n"})
    assert error is not None
    assert "unsupported filename" in error


def test_validate_code_files_rejects_syntax_errors():
    error = _validate_code_files({"calculator.py": "def broken(:\n"})
    assert error is not None
    assert "invalid Python" in error


def test_clean_plan_removes_blank_steps():
    assert _clean_plan(["  first  ", "", "   ", "second"]) == ["first", "second"]


async def test_analyst_node_uses_fallback_when_plan_stays_empty(monkeypatch):
    async def empty_plan(self, state):
        return PlanOutput(steps=["", "   "])

    monkeypatch.setattr(graph_nodes, "get_pool", lambda: object())
    monkeypatch.setattr(graph_nodes.AnalystAgent, "run", empty_plan)

    update = await analyst_node({"task": "x"})

    assert update["plan"] == ["Implement directly from the task description."]


async def test_rag_node_reports_disabled_status():
    update = await rag_node({"task": "x", "use_rag": False})

    assert update["rag_status"] == "disabled"
    assert update["rag_chunk_count"] == 0


async def test_rag_node_reports_unavailable_status(monkeypatch):
    def unavailable(query):
        return RetrievalResult(
            chunks=[],
            status="unavailable",
            message="RAG retrieval unavailable: boom",
        )

    monkeypatch.setattr(graph_nodes, "retrieve_with_status", unavailable)

    update = await rag_node({"task": "x"})

    assert update["rag_status"] == "unavailable"
    assert update["rag_chunk_count"] == 0
    assert "boom" in update["rag_message"]


async def test_rag_node_reports_retrieved_status(monkeypatch):
    def retrieved(query):
        return RetrievalResult(
            chunks=[RetrievedChunk(text="Use type hints.", source="style.md")],
            status="retrieved",
            message="Retrieved 1 RAG chunk(s).",
        )

    monkeypatch.setattr(graph_nodes, "retrieve_with_status", retrieved)

    update = await rag_node({"task": "x"})

    assert update["rag_status"] == "retrieved"
    assert update["rag_chunk_count"] == 1
    assert update["rag_sources"] == ["style.md"]
