"""QA routing node."""

from __future__ import annotations

import ast
from typing import Any

from loguru import logger

from app.agents.qa import QAAgent
from app.config import settings
from app.graph.advisory_qa import advisory_qa_update as _advisory_qa_update
from app.graph.code_utils import strip_code_fences as _strip_code_fences
from app.graph.error_boundary import node_error_boundary
from app.graph.pytest_utils import build_test_imports as _build_test_imports
from app.graph.pytest_utils import parse_pytest as _parse_pytest
from app.graph.state import AgentState, FeedbackItem, TestResults
from app.graph.static_web_qa import static_web_qa_update as _static_web_qa_update
from app.llm.pool import get_pool
from app.tools.mcp_client import workspace_tools


@node_error_boundary
async def qa_node(state: AgentState) -> dict[str, Any]:
    """Run profile-specific QA and fold test failures into review feedback."""
    if state.get("task_profile") == "static_web":
        return _static_web_qa_update(state)
    if state.get("task_profile") in {"docs", "project"}:
        return _advisory_qa_update(state)

    result = await QAAgent(get_pool()).run(state)

    task_rel = f"task-{state.get('task_id') or 'unknown'}"
    code = state.get("code") or {}
    test_code = _strip_code_fences(result.test_code)
    test_file = _build_test_imports(test_code, code) + test_code

    try:
        ast.parse(test_file)
    except SyntaxError as exc:
        logger.warning(f"QA produced a syntactically invalid test: {exc}")
        output = f"QA test generation failed -- syntax error: {exc}"
        return {
            "test_code": test_file,
            "test_cases": result.test_cases,
            "test_results": TestResults(
                passed=0,
                failed=1,
                total=1,
                output=output,
            ),
            "node_error": f"qa_node: {output}",
            "should_abort": True,
            "status": "FAILED",
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
        "test_cases": result.test_cases,
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
