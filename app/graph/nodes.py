"""LangGraph nodes that wrap the LLM agents.

Each node runs one agent against the workflow state and returns a state
update. The QA node additionally writes the code and tests to disk and runs
pytest, since the workflow's looping decision depends on real test results.
"""

from __future__ import annotations

import ast
import asyncio
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from app.agents.analyst import AnalystAgent
from app.agents.developer import DeveloperAgent
from app.agents.qa import QAAgent
from app.agents.reviewer import ReviewerAgent
from app.config import settings
from app.graph.error_boundary import node_error_boundary
from app.graph.state import AgentState, FeedbackItem, TestResults
from app.llm.pool import get_pool


@node_error_boundary
async def analyst_node(state: AgentState) -> dict[str, Any]:
    """Run the Analyst to produce an implementation plan."""
    result = await AnalystAgent(get_pool()).run(state)
    return {"plan": result.steps}


@node_error_boundary
async def developer_node(state: AgentState) -> dict[str, Any]:
    """Run the Developer to generate or revise the code."""
    result = await DeveloperAgent(get_pool()).run(state)
    return {
        "code": {
            f.filename: _strip_code_fences(f.content) for f in result.files
        }
    }


@node_error_boundary
async def reviewer_node(state: AgentState) -> dict[str, Any]:
    """Run the Reviewer to inspect the current code."""
    result = await ReviewerAgent(get_pool()).run(state)
    return {"review_feedback": result.findings}


@node_error_boundary
async def qa_node(state: AgentState) -> dict[str, Any]:
    """Run the QA agent, write code and tests to disk, and run pytest.

    A test failure is folded into ``review_feedback`` as a BLOCKER finding so
    the Developer sees it through the same channel as review findings.
    """
    result = await QAAgent(get_pool()).run(state)

    task_dir = _task_dir(state)
    task_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in (state.get("code") or {}).items():
        (task_dir / filename).write_text(content)
    test_code = _strip_code_fences(result.test_code)
    test_header = _build_test_imports(test_code, state.get("code") or {})
    (task_dir / result.test_filename).write_text(test_header + test_code)

    test_results = await asyncio.to_thread(_run_pytest, task_dir)
    update: dict[str, Any] = {"test_results": test_results}

    if test_results.failed > 0:
        feedback = list(state.get("review_feedback") or [])
        feedback.append(
            FeedbackItem(
                severity="BLOCKER",
                issue=f"{test_results.failed} test(s) failed.",
                suggestion="Fix the implementation so that all tests pass.",
            )
        )
        update["review_feedback"] = feedback

    return update


def _task_dir(state: AgentState) -> Path:
    """Return the isolated workspace directory for the current task."""
    return settings.workspace_dir / f"task-{state['task_id']}"


def _run_pytest(task_dir: Path) -> TestResults:
    """Run pytest in the task directory under a hard timeout.

    The timeout (EC-11) prevents an infinite loop in generated code from
    freezing the whole workflow.
    """
    try:
        proc = subprocess.run(
            [
                sys.executable, "-m", "pytest",
                "-q", "--tb=short", "-p", "no:cacheprovider",
            ],
            cwd=str(task_dir),
            capture_output=True,
            text=True,
            timeout=settings.test_timeout,
        )
    except subprocess.TimeoutExpired:
        logger.warning("pytest timed out -- treating as a failed test")
        return TestResults(
            passed=0,
            failed=1,
            total=1,
            output="test execution timed out -- possible infinite loop",
        )

    output = proc.stdout + proc.stderr
    passed = _count(r"(\d+) passed", output)
    failed = _count(r"(\d+) failed", output) + _count(r"(\d+) error", output)
    logger.info(f"pytest: {passed} passed, {failed} failed")
    return TestResults(
        passed=passed,
        failed=failed,
        total=passed + failed,
        output=output[-2000:],
    )


def _count(pattern: str, text: str) -> int:
    """Extract a leading integer count from pytest summary output."""
    match = re.search(pattern, text)
    return int(match.group(1)) if match else 0


def _strip_code_fences(text: str) -> str:
    """Remove a wrapping markdown code fence from LLM output, if present.

    Models sometimes wrap code in a ```python ... ``` fence even inside a
    structured string field. Writing that verbatim to a .py file produces a
    syntax error, so the fence is stripped before the code reaches disk.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return text
    lines = stripped.splitlines()[1:]  # drop the opening fence line
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]  # drop the closing fence line
    return "\n".join(lines)


def _public_names(code: str) -> list[str]:
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


def _build_test_imports(test_code: str, code: dict[str, str]) -> str:
    """Build the import lines a generated test file is missing.

    The QA agent sometimes omits imports. This derives the needed imports from
    the actual code (via AST) and returns only the lines not already present,
    so the generated test file is always runnable.
    """
    lines: list[str] = []
    if not re.search(r"^\s*import\s+pytest\b", test_code, re.MULTILINE):
        lines.append("import pytest")
    for filename, content in code.items():
        module = filename.removesuffix(".py")
        if re.search(rf"\b(from|import)\s+{re.escape(module)}\b", test_code):
            continue
        names = _public_names(content)
        if names:
            lines.append(f"from {module} import {', '.join(names)}")
    return "\n".join(lines) + "\n\n" if lines else ""
