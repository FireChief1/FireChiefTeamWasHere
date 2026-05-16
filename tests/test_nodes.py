"""Tests for the pure helper functions used by the workflow nodes."""

from __future__ import annotations

import pytest

from app.graph.nodes import (
    _build_test_imports,
    _count,
    _parse_pytest,
    _public_names,
    _strip_code_fences,
)


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
