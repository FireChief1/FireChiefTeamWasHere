"""Deterministic structural QA for Node.js/JavaScript artifacts.

This is the interim QA for the node_js profile: it validates structure without
executing code. Real test execution (node --check, node:test) is added through
the workspace MCP server as a follow-up and will replace these checks for
environments where Node is available.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from app.agents.javascript_qa import JavaScriptQAAgent
from app.config import settings
from app.graph.code_utils import strip_code_fences
from app.graph.state import AgentState, FeedbackItem, TestResults
from app.graph.static_web_qa import record_check
from app.llm.pool import get_pool
from app.tools.mcp_client import workspace_tools

_SCRIPT_SUFFIXES = {".js", ".mjs", ".cjs"}
_NODE_TEST_FILENAME = "generated.test.mjs"
_PACKAGE_JSON = '{\n  "type": "module"\n}\n'


def _as_int(value: object) -> int:
    """Coerce a JSON report value to int, defaulting to 0."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


async def run_node_qa(state: AgentState) -> dict[str, Any]:
    """Execute Node.js tests when the toolchain is available, else fall back.

    Generates a node:test suite, writes the code + a package.json (type module)
    + the test file to the isolated task workspace, and runs them. When Node is
    not installed (or no tests are discovered), it degrades to the deterministic
    structural checks in ``node_qa_update``.
    """
    try:
        result = await JavaScriptQAAgent(get_pool()).run(state)
    except Exception as exc:  # noqa: BLE001 - fall back to structural QA
        logger.warning(f"Node QA generation failed; using structural checks: {exc}")
        return node_qa_update(state)

    code = state.get("code") or {}
    task_rel = f"task-{state.get('task_id') or 'unknown'}"
    test_code = strip_code_fences(result.test_code)

    async with workspace_tools() as tools:
        for filename, content in code.items():
            await tools.write_file(f"{task_rel}/{filename}", content)
        await tools.write_file(f"{task_rel}/package.json", _PACKAGE_JSON)
        await tools.write_file(f"{task_rel}/{_NODE_TEST_FILENAME}", test_code)
        report = await tools.run_node_tests(task_rel, timeout=settings.test_timeout)

    total = _as_int(report.get("total"))
    if not report.get("available") or total == 0:
        # Node missing or no executable tests discovered -> structural fallback.
        return node_qa_update(state)

    failed = _as_int(report.get("failed"))
    output = str(report.get("output") or "")
    update: dict[str, Any] = {
        "test_results": TestResults(
            passed=_as_int(report.get("passed")),
            failed=failed,
            total=total,
            output=output,
        ),
        "test_code": test_code,
        "test_cases": result.test_cases,
    }
    if failed > 0:
        feedback = list(state.get("review_feedback") or [])
        feedback.append(
            FeedbackItem(
                severity="BLOCKER",
                issue=f"{failed} Node test(s) failed:\n{output[-1500:]}",
                suggestion="Fix the implementation so every failing test passes.",
            )
        )
        update["review_feedback"] = feedback
    return update


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
