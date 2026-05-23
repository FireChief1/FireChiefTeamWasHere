"""Read-only Project Mode intake for repository context."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT
from app.graph.error_boundary import node_error_boundary
from app.graph.state import AgentState
from app.tools.mcp_client import project_tools

_EXCERPT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yml",
    ".yaml",
}
_PROJECT_FALLBACK_FILES = (
    "README.md",
    "docs/architecture.md",
    "app/graph/workflow.py",
    "app/graph/nodes.py",
    "app/graph/state.py",
    "app/ui/streamlit_app.py",
)
_PROJECT_STOPWORDS = {
    "about",
    "after",
    "again",
    "bana",
    "bunu",
    "daha",
    "detaylı",
    "devam",
    "elim",
    "hadi",
    "icin",
    "için",
    "mode",
    "olan",
    "olarak",
    "project",
    "proje",
    "projeyi",
    "şimdi",
    "this",
    "with",
    "yapalım",
}


@node_error_boundary
async def project_intake_node(state: AgentState) -> dict[str, Any]:
    """Gather repository context for project-mode runs."""
    if state.get("mode") != "project":
        return {}

    focus_terms = project_focus_terms(state["task"])
    search_pattern = "|".join(re.escape(term) for term in focus_terms)
    project_path = project_path_from_state(state)

    async with project_tools(project_path) as tools:
        mcp_root = Path(await tools.root_path()).expanduser().resolve()
        if mcp_root != project_path:
            return _path_mismatch_update(project_path, mcp_root)
        files = await tools.list_files(max_files=250)
        matches = (
            await tools.search_text(search_pattern, max_matches=60)
            if search_pattern
            else []
        )
        relevant_files = project_relevant_files(files, matches)
        file_excerpts = await project_file_excerpts(tools, relevant_files)
        git_status = await tools.git_status()
        git_diff = await tools.git_diff(max_chars=6000)

    return {
        "project_files": files,
        "project_relevant_files": relevant_files,
        "project_search_matches": matches,
        "project_file_excerpts": file_excerpts,
        "project_git_status": git_status,
        "project_git_diff": git_diff,
        "project_path": str(project_path),
        "project_mcp_root": str(mcp_root),
        "project_path_mismatch": False,
        "project_summary": project_summary(
            files=files,
            matches=matches,
            relevant_files=relevant_files,
            git_status=git_status,
        ),
        "project_focus_terms": focus_terms,
    }


def _path_mismatch_update(project_path: Path, mcp_root: Path) -> dict[str, Any]:
    """Return a fail-safe update when MCP did not bind to the selected folder."""
    message = (
        "Project path mismatch: selected folder and MCP root differ. "
        f"Selected: {project_path}. MCP root: {mcp_root}."
    )
    return {
        "project_files": [],
        "project_relevant_files": [],
        "project_search_matches": [],
        "project_file_excerpts": [],
        "project_git_status": "",
        "project_git_diff": "",
        "project_path": str(project_path),
        "project_mcp_root": str(mcp_root),
        "project_path_mismatch": True,
        "project_summary": message,
        "project_focus_terms": [],
        "node_error": f"project_intake_node: {message}",
        "should_abort": True,
        "status": "FAILED",
    }


def project_path_from_state(state: AgentState) -> Path:
    """Return the selected project folder, defaulting to this repository."""
    raw_path = state.get("project_path") or str(PROJECT_ROOT)
    return Path(raw_path).expanduser().resolve()


def project_focus_terms(task: str) -> list[str]:
    """Extract a small, deterministic set of search terms from a task."""
    terms: list[str] = []
    for raw_term in re.findall(r"[\w./-]{4,}", task.casefold()):
        term = raw_term.strip("._/-")
        if not term or term in _PROJECT_STOPWORDS or term in terms:
            continue
        terms.append(term)
        if len(terms) >= 6:
            break
    return terms


def project_relevant_files(
    files: list[str], matches: list[dict[str, object]]
) -> list[str]:
    """Select the most useful project files to show downstream agents."""
    relevant: list[str] = []
    for match in matches:
        filename = match.get("file")
        if isinstance(filename, str) and filename not in relevant:
            relevant.append(filename)
        if len(relevant) >= 12:
            return relevant

    for filename in _PROJECT_FALLBACK_FILES:
        if filename in files and filename not in relevant:
            relevant.append(filename)
        if len(relevant) >= 12:
            return relevant

    return relevant or files[:12]


async def project_file_excerpts(
    tools: Any,
    relevant_files: list[str],
    *,
    max_files: int = 6,
    max_chars: int = 1600,
) -> list[dict[str, object]]:
    """Read small relevant-file excerpts to ground downstream agents."""
    excerpts: list[dict[str, object]] = []
    for filename in relevant_files:
        if len(excerpts) >= max_files:
            break
        if Path(filename).suffix.casefold() not in _EXCERPT_SUFFIXES:
            continue
        try:
            content = await tools.read_file(filename)
        except Exception:
            continue
        excerpts.append(
            {
                "file": filename,
                "content": content[:max_chars],
                "truncated": len(content) > max_chars,
            }
        )
    return excerpts


def project_summary(
    *,
    files: list[str],
    matches: list[dict[str, object]],
    relevant_files: list[str],
    git_status: str,
) -> str:
    """Build a compact project-intake summary."""
    if "not a git repository" in git_status:
        repository_state = "a non-git folder"
    else:
        dirty_lines = [
            line
            for line in git_status.splitlines()
            if line.strip() and not line.startswith("## ")
        ]
        repository_state = f"a {'dirty' if dirty_lines else 'clean'} git tree"
    return (
        f"Project intake scanned {len(files)} text-oriented files, found "
        f"{len(matches)} task-related matches, selected "
        f"{len(relevant_files)} relevant files, and saw {repository_state}."
    )
