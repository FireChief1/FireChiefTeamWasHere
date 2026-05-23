"""Developer routing node and project advisory fallback."""

from __future__ import annotations

import re
from typing import Any

from loguru import logger

from app.agents.developer import DeveloperAgent
from app.agents.docs_advisor import DocsAdvisorAgent
from app.agents.project_advisor import ProjectAdvisorAgent
from app.agents.static_web_developer import StaticWebDeveloperAgent
from app.graph.code_utils import strip_code_fences as _strip_code_fences
from app.graph.code_validation import validate_code_files as _validate_code_files
from app.graph.error_boundary import node_error_boundary
from app.graph.state import AgentState
from app.llm.pool import get_pool


@node_error_boundary
async def developer_node(state: AgentState) -> dict[str, Any]:
    """Run the profile-specific Developer to generate or revise code."""
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
