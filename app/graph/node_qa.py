"""Deterministic structural QA for Node.js/JavaScript artifacts.

This is the interim QA for the node_js profile: it validates structure without
executing code. Real test execution (node --check, node:test) is added through
the workspace MCP server as a follow-up and will replace these checks for
environments where Node is available.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.graph.state import AgentState, FeedbackItem, TestResults
from app.graph.static_web_qa import record_check

_SCRIPT_SUFFIXES = {".js", ".mjs", ".cjs"}


def node_qa_update(state: AgentState) -> dict[str, Any]:
    """Run deterministic Node.js validation instead of executing tests."""
    code = state.get("code") or {}
    passes: list[str] = []
    failures: list[str] = []

    scripts = {
        name: content
        for name, content in code.items()
        if Path(name).suffix.casefold() in _SCRIPT_SUFFIXES
    }
    record_check(
        bool(scripts),
        "At least one JavaScript file is present.",
        passes,
        failures,
    )
    for name, content in scripts.items():
        record_check(
            content.count("{") == content.count("}"),
            f"{name}: braces are balanced.",
            passes,
            failures,
            failure_detail=f"{name}: unbalanced braces.",
        )
        record_check(
            content.count("(") == content.count(")"),
            f"{name}: parentheses are balanced.",
            passes,
            failures,
            failure_detail=f"{name}: unbalanced parentheses.",
        )
        record_check(
            "export" in content or "module.exports" in content,
            f"{name}: exports a public API.",
            passes,
            failures,
            failure_detail=f"{name}: nothing is exported for import/testing.",
        )

    results = TestResults(
        passed=len(passes),
        failed=len(failures),
        total=len(passes) + len(failures),
        output="\n".join([*passes, *failures]),
    )
    update: dict[str, Any] = {
        "test_results": results,
        "test_code": "Node.js structural validation ran without execution.",
        "test_cases": [*passes, *failures],
    }
    if failures:
        feedback = list(state.get("review_feedback") or [])
        feedback.append(
            FeedbackItem(
                severity="BLOCKER",
                issue="Node.js validation failed:\n" + "\n".join(failures),
                suggestion="Fix the generated JavaScript and export the public API.",
            )
        )
        update["review_feedback"] = feedback
    return update
