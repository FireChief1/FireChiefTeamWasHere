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
from app.agents.docs_advisor import DocsAdvisorAgent, DocsAdvisorReviewerAgent
from app.agents.project_advisor import ProjectAdvisorAgent, ProjectAdvisorReviewerAgent
from app.agents.qa import QAAgent
from app.agents.reviewer import ReviewerAgent
from app.agents.static_web_developer import StaticWebDeveloperAgent
from app.agents.static_web_reviewer import StaticWebReviewerAgent
from app.config import settings
from app.graph.advisory_qa import advisory_qa_update as _advisory_qa_update
from app.graph.code_utils import strip_code_fences as _strip_code_fences
from app.graph.code_validation import validate_code_files as _validate_code_files
from app.graph.error_boundary import node_error_boundary
from app.graph.project_brief import project_brief_node
from app.graph.project_intake import project_intake_node
from app.graph.pytest_utils import build_test_imports as _build_test_imports
from app.graph.pytest_utils import parse_pytest as _parse_pytest
from app.graph.state import AgentState, FeedbackItem, TestResults
from app.graph.static_web_qa import static_web_qa_update as _static_web_qa_update
from app.graph.task_profile import classify_task_profile
from app.llm.pool import get_pool
from app.rag.retriever import retrieve_with_status
from app.tools.mcp_client import workspace_tools

_ANALYST_FALLBACK_PLAN = ["Implement directly from the task description."]

__all__ = [
    "analyst_node",
    "developer_node",
    "project_brief_node",
    "project_intake_node",
    "qa_node",
    "rag_node",
    "reviewer_node",
    "task_classifier_node",
]


@node_error_boundary
async def task_classifier_node(state: AgentState) -> dict[str, Any]:
    """Select the implementation profile used by downstream nodes."""
    profile, reason = classify_task_profile(state)
    logger.info(f"task profile: {profile} ({reason})")
    return {"task_profile": profile, "task_profile_reason": reason}


@node_error_boundary
async def rag_node(state: AgentState) -> dict[str, Any]:
    """Retrieve coding-standard chunks relevant to the task (RAG).

    Runs first so every agent downstream sees the retrieved context. If the
    knowledge base is unavailable, the workflow continues without context.
    """
    if state.get("use_rag") is False:
        logger.info("RAG: disabled for this run")
        return {
            "rag_context": [],
            "rag_sources": [],
            "rag_status": "disabled",
            "rag_message": "RAG disabled for this run.",
            "rag_chunk_count": 0,
        }
    retrieval = await asyncio.to_thread(
        retrieve_with_status,
        state["task"],
        profile=state.get("task_profile"),
    )
    chunks = retrieval.chunks
    logger.info(f"RAG: retrieved {len(chunks)} chunk(s)")
    if not chunks:
        return {
            "rag_context": [],
            "rag_sources": [],
            "rag_status": retrieval.status,
            "rag_message": retrieval.message,
            "rag_chunk_count": 0,
        }
    return {
        "rag_context": [f"[{chunk.source}]\n{chunk.text}" for chunk in chunks],
        "rag_sources": [chunk.source for chunk in chunks],
        "rag_status": "retrieved",
        "rag_message": retrieval.message,
        "rag_chunk_count": len(chunks),
    }


@node_error_boundary
async def analyst_node(state: AgentState) -> dict[str, Any]:
    """Run the Analyst to produce an implementation plan."""
    agent = AnalystAgent(get_pool())
    result = await agent.run(state)
    plan = _clean_plan(result.steps)
    if not plan:
        logger.warning("Analyst produced an empty plan; retrying once")
        result = await agent.run(state)
        plan = _clean_plan(result.steps)
    if not plan:
        logger.warning("Analyst plan fallback activated")
        plan = list(_ANALYST_FALLBACK_PLAN)
    return {"plan": plan}


def _clean_plan(steps: list[str]) -> list[str]:
    """Remove blank plan steps while preserving order."""
    return [step.strip() for step in steps if step.strip()]


@node_error_boundary
async def developer_node(state: AgentState) -> dict[str, Any]:
    """Run the Developer to generate or revise the code.

    If the generated code is syntactically broken, the Developer is given one
    more attempt before the code flows downstream to the Reviewer and QA.
    """
    agent = _developer_for_profile(state)
    result = await agent.run(state)
    code = {f.filename: _strip_code_fences(f.content) for f in result.files}
    validation_error = _validate_code_files(
        code,
        profile=state.get("task_profile", "python"),
    )

    if validation_error:
        logger.warning(
            f"Developer produced invalid code; retrying once: {validation_error}"
        )
        result = await agent.run(state)
        code = {f.filename: _strip_code_fences(f.content) for f in result.files}
        validation_error = _validate_code_files(
            code,
            profile=state.get("task_profile", "python"),
        )

    if validation_error:
        if state.get("task_profile") == "project":
            logger.warning("Project advisor fallback activated")
            return _project_advisory_fallback_update(state, validation_error)
        logger.error(f"Developer output rejected: {validation_error}")
        return {
            "code": code,
            "dev_approach": result.approach,
            "dev_assumptions": result.assumptions,
            "node_error": f"developer_node: {validation_error}",
            "should_abort": True,
            "status": "FAILED",
        }

    return {
        "code": code,
        "dev_approach": _clean_developer_approach(result.approach, result.summary),
        "dev_assumptions": result.assumptions,
    }


def _clean_developer_approach(approach: str, summary: str) -> str:
    """Return a useful approach string even when the LLM gives a format label."""
    cleaned = approach.strip()
    if cleaned.casefold() in {"markdown", "md", "text", "plain text"}:
        fallback = summary.strip()
        return fallback or "Produced the requested output for the selected profile."
    return cleaned


def _project_advisory_fallback_update(
    state: AgentState,
    validation_error: str,
) -> dict[str, Any]:
    """Return a deterministic project proposal when the advisor misroutes."""
    proposal = _project_advisory_fallback_markdown(state, validation_error)
    return {
        "code": {"PROJECT_PROPOSAL.md": proposal},
        "dev_approach": (
            "Generated a deterministic advisory proposal because the model "
            "did not return a valid project advisory file."
        ),
        "dev_assumptions": [
            "The user asked for project-level analysis or planning.",
            "Existing project source/artifact files should not be overwritten.",
        ],
    }


def _project_advisory_fallback_markdown(
    state: AgentState,
    validation_error: str,
) -> str:
    """Build a grounded PROJECT_PROPOSAL.md without asking the LLM again."""
    task = str(state.get("task") or "Project analysis")
    summary = str(state.get("project_summary") or "Project intake completed.")
    relevant_files = [str(item) for item in state.get("project_relevant_files") or []]
    risks = [str(item) for item in state.get("project_risks") or []]
    subjects = _observed_project_subjects(state)

    lines = [
        "# Project Proposal",
        "",
        "## Observations",
        f"- Requested task: {task}",
        f"- Project intake: {summary}",
    ]
    if subjects:
        lines.append("- Observed subject matter: " + ", ".join(subjects[:4]))
    if relevant_files:
        lines.append(
            "- Relevant files: "
            + ", ".join(f"`{name}`" for name in relevant_files[:8])
        )

    lines.extend(["", "## Risks"])
    if risks:
        lines.extend(f"- {risk}" for risk in risks[:5])
    lines.append(
        "- The advisor model returned an invalid advisory artifact, so this "
        f"fallback avoided source changes. Validation detail: {validation_error}"
    )

    lines.extend(
        [
            "",
            "## Recommended Next Steps",
            "1. Keep this run advisory-only and review the current project facts.",
            "2. Choose one concrete follow-up change before editing source files.",
            "3. Run the detected project checks after any implementation change.",
        ]
    )
    return "\n".join(lines) + "\n"


def _observed_project_subjects(state: AgentState) -> list[str]:
    """Extract visible page/document subjects from project file excerpts."""
    subjects: list[str] = []
    excerpts = state.get("project_file_excerpts") or []
    for excerpt in excerpts:
        if not isinstance(excerpt, dict):
            continue
        content = excerpt.get("content")
        if not isinstance(content, str):
            continue
        for pattern in (
            r"<title[^>]*>(?P<text>.*?)</title>",
            r"<h1[^>]*>(?P<text>.*?)</h1>",
            r"^#\s+(?P<text>.+)$",
        ):
            for match in re.finditer(
                pattern,
                content,
                flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
            ):
                subject = re.sub(r"\s+", " ", match.group("text")).strip()
                if len(subject) > 120:
                    subject = subject[:117].rstrip() + "..."
                if subject and subject not in subjects:
                    subjects.append(subject)
    return subjects


def _developer_for_profile(state: AgentState) -> DeveloperAgent:
    """Return the Developer persona for the current task profile."""
    if state.get("task_profile") == "static_web":
        return StaticWebDeveloperAgent(get_pool())
    if state.get("task_profile") == "docs":
        return DocsAdvisorAgent(get_pool())
    if state.get("task_profile") == "project":
        return ProjectAdvisorAgent(get_pool())
    return DeveloperAgent(get_pool())


@node_error_boundary
async def reviewer_node(state: AgentState) -> dict[str, Any]:
    """Run the Reviewer to inspect the current code."""
    agent = (
        StaticWebReviewerAgent(get_pool())
        if state.get("task_profile") == "static_web"
        else DocsAdvisorReviewerAgent(get_pool())
        if state.get("task_profile") == "docs"
        else ProjectAdvisorReviewerAgent(get_pool())
        if state.get("task_profile") == "project"
        else ReviewerAgent(get_pool())
    )
    result = await agent.run(state)
    return {"review_feedback": result.findings}


@node_error_boundary
async def qa_node(state: AgentState) -> dict[str, Any]:
    """Run the QA agent, then write code and tests and run pytest via MCP.

    A test failure is folded into ``review_feedback`` as a BLOCKER finding
    carrying the pytest output, so the Developer sees the specific failures.
    """
    if state.get("task_profile") == "static_web":
        return _static_web_qa_update(state)
    if state.get("task_profile") in {"docs", "project"}:
        return _advisory_qa_update(state)

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
