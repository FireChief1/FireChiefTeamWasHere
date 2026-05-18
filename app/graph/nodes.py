"""LangGraph nodes that wrap the LLM agents.

Each node runs one agent against the workflow state and returns a state
update. The QA node additionally writes the code and tests and runs pytest --
all through the workspace MCP server, which enforces the workspace boundary.
"""

from __future__ import annotations

import ast
import asyncio
import re
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
from app.rag.retriever import retrieve
from app.tools.mcp_client import workspace_tools


@node_error_boundary
async def rag_node(state: AgentState) -> dict[str, Any]:
    """Retrieve coding-standard chunks relevant to the task (RAG).

    Runs first so every agent downstream sees the retrieved context. If the
    knowledge base is unavailable, the workflow continues without context.
    """
    if state.get("use_rag") is False:
        logger.info("RAG: disabled for this run")
        return {"rag_context": [], "rag_sources": []}
    chunks = await asyncio.to_thread(retrieve, state["task"])
    logger.info(f"RAG: retrieved {len(chunks)} chunk(s)")
    return {
        "rag_context": [f"[{chunk.source}]\n{chunk.text}" for chunk in chunks],
        "rag_sources": [chunk.source for chunk in chunks],
    }


@node_error_boundary
async def analyst_node(state: AgentState) -> dict[str, Any]:
    """Run the Analyst to produce an implementation plan."""
    result = await AnalystAgent(get_pool()).run(state)
    return {"plan": result.steps}


@node_error_boundary
async def developer_node(state: AgentState) -> dict[str, Any]:
    """Run the Developer to generate or revise the code.

    If the generated code is syntactically broken, the Developer is given one
    more attempt before the code flows downstream to the Reviewer and QA.
    """
    agent = DeveloperAgent(get_pool())
    result = await agent.run(state)
    code = {f.filename: _strip_code_fences(f.content) for f in result.files}

    if not _all_parseable(code):
        logger.warning("Developer produced unparseable code; retrying once")
        result = await agent.run(state)
        code = {f.filename: _strip_code_fences(f.content) for f in result.files}

    return {
        "code": code,
        "dev_approach": result.approach,
        "dev_assumptions": result.assumptions,
    }


def _all_parseable(code: dict[str, str]) -> bool:
    """Return True if every generated file parses as valid Python."""
    for content in code.values():
        try:
            ast.parse(content)
        except SyntaxError:
            return False
    return True


@node_error_boundary
async def reviewer_node(state: AgentState) -> dict[str, Any]:
    """Run the Reviewer to inspect the current code."""
    result = await ReviewerAgent(get_pool()).run(state)
    return {"review_feedback": result.findings}


@node_error_boundary
async def qa_node(state: AgentState) -> dict[str, Any]:
    """Run the QA agent, then write code and tests and run pytest via MCP.

    A test failure is folded into ``review_feedback`` as a BLOCKER finding
    carrying the pytest output, so the Developer sees the specific failures.
    """
    result = await QAAgent(get_pool()).run(state)

    task_rel = f"task-{state['task_id']}"
    code = state.get("code") or {}
    test_code = _strip_code_fences(result.test_code)
    test_file = _build_test_imports(test_code, code) + test_code

    # Guard: a syntactically broken test would poison the loop with a BLOCKER
    # the Developer cannot fix. Skip running it instead of failing the task.
    try:
        ast.parse(test_file)
    except SyntaxError as exc:
        logger.warning(f"QA produced a syntactically invalid test: {exc}")
        return {
            "test_code": test_file,
            "test_results": TestResults(
                passed=0,
                failed=0,
                total=0,
                output=f"QA test skipped -- syntax error: {exc}",
            ),
        }

    async with workspace_tools() as tools:
        for filename, content in code.items():
            await tools.write_file(f"{task_rel}/{filename}", content)
        await tools.write_file(f"{task_rel}/{result.test_filename}", test_file)
        output = await tools.run_pytest(task_rel, timeout=settings.test_timeout)

    test_results = _parse_pytest(output)
    update: dict[str, Any] = {
        "test_results": test_results,
        "test_code": test_file,
    }

    if test_results.failed > 0:
        feedback = list(state.get("review_feedback") or [])
        feedback.append(
            FeedbackItem(
                severity="BLOCKER",
                issue=(
                    f"{test_results.failed} test(s) failed. The pytest output "
                    f"below shows exactly which tests failed and why:\n"
                    f"{test_results.output[-1500:]}"
                ),
                suggestion=(
                    "Fix the implementation so every failing test passes. "
                    "Address the specific assertion errors and exceptions shown."
                ),
            )
        )
        update["review_feedback"] = feedback

    return update


def _parse_pytest(output: str) -> TestResults:
    """Parse raw pytest output into a TestResults summary."""
    if output.startswith("TIMEOUT:"):
        return TestResults(passed=0, failed=1, total=1, output=output)
    passed = _count(r"(\d+) passed", output)
    failed = _count(r"(\d+) failed", output) + _count(r"(\d+) error", output)
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
