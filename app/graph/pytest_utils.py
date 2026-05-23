"""Pytest parsing and generated-test import helpers."""

from __future__ import annotations

import ast
import re

from app.graph.state import TestResults


def parse_pytest(output: str) -> TestResults:
    """Parse raw pytest output into a TestResults summary."""
    if output.startswith("TIMEOUT:"):
        return TestResults(passed=0, failed=1, total=1, output=output)
    if "no tests ran" in output or "collected 0 items" in output:
        return TestResults(
            passed=0,
            failed=1,
            total=1,
            output=(output or "No tests were collected or executed.")[-2000:],
        )
    passed = count_pattern(r"(\d+) passed", output)
    failed = count_pattern(r"(\d+) failed", output) + count_pattern(
        r"(\d+) error", output
    )
    total = passed + failed
    if total == 0:
        return TestResults(
            passed=0,
            failed=1,
            total=1,
            output=(
                output
                or "Pytest completed without any passing or failing tests."
            )[-2000:],
        )
    return TestResults(
        passed=passed,
        failed=failed,
        total=total,
        output=output[-2000:],
    )


def count_pattern(pattern: str, text: str) -> int:
    """Extract a leading integer count from pytest summary output."""
    match = re.search(pattern, text)
    return int(match.group(1)) if match else 0


def public_names(code: str) -> list[str]:
    """Return the top-level class and function names defined in source code."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    return [
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and not node.name.startswith("_")
    ]


def build_test_imports(test_code: str, code: dict[str, str]) -> str:
    """Build the import lines a generated test file is missing."""
    lines: list[str] = []
    if not re.search(r"^\s*import\s+pytest\b", test_code, re.MULTILINE):
        lines.append("import pytest")
    for filename, content in code.items():
        module = filename.removesuffix(".py")
        if re.search(rf"\b(from|import)\s+{re.escape(module)}\b", test_code):
            continue
        names = public_names(content)
        if names:
            lines.append(f"from {module} import {', '.join(names)}")
    return "\n".join(lines) + "\n\n" if lines else ""
