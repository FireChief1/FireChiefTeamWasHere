"""Bounded, model-driven file discovery for Project Mode.

Project Intake selects a small, deterministic set of relevant files. When the
optional explore step is enabled, the model is given a tight, budgeted loop to
request a few more files to read or searches to run, so it can gather its own
context before the workflow proceeds -- a first step toward "working on a
project" rather than only seeing pre-selected files.

Safety is preserved: the model only chooses *which* file to read or *what* to
search; the node executes it through the already-sandboxed workspace MCP tools.
The loop is bounded by a step count and a byte budget, and reads are restricted
to listed files with known text suffixes.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel, Field

ExploreAction = Literal["read_file", "search_text", "done"]

# Reuse the same text-file allow-list the deterministic excerpt reader uses.
_EXPLORE_SUFFIXES = {
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

_EXPLORE_SYSTEM = (
    "You are exploring an existing code project to gather just enough context "
    "to complete a task. You may read one listed file at a time, run one text "
    "search, or stop. Choose the single most useful next action. Do not ask to "
    "read a file you have already read. Stop with action 'done' as soon as you "
    "have enough context; do not explore more than necessary."
)


class ExploreDecision(BaseModel):
    """One step of the bounded project exploration loop."""

    action: ExploreAction = Field(
        description="read_file, search_text, or done.",
    )
    target: str = Field(
        default="",
        description=(
            "For read_file: an exact path from the available files list. "
            "For search_text: a short keyword. Empty for done."
        ),
    )
    reason: str = Field(default="", description="Why this step helps the task.")


ExploreDecider = Callable[[str], Awaitable[ExploreDecision]]


async def explore_project_files(
    *,
    task: str,
    tools: Any,
    candidate_files: list[str],
    seen_excerpts: list[dict[str, object]],
    max_steps: int,
    max_bytes: int,
    max_chars_per_file: int = 1600,
    decide: ExploreDecider | None = None,
) -> list[dict[str, object]]:
    """Run a bounded discovery loop and return newly read file excerpts.

    Args:
        task: The task driving the exploration.
        tools: An open workspace/project MCP tools session (sandboxed to root).
        candidate_files: Files the model is allowed to read (from intake).
        seen_excerpts: Excerpts already gathered deterministically.
        max_steps: Maximum number of model decisions.
        max_bytes: Total byte budget across newly read files.
        max_chars_per_file: Per-file excerpt cap.
        decide: Injectable decision function (defaults to the local model).

    Returns:
        The list of newly discovered excerpts (never includes already-seen
        files). Returns an empty list on any failure -- exploration is optional.
    """
    if max_steps <= 0 or max_bytes <= 0 or not candidate_files:
        return []

    decider = decide or _model_explore_decision
    candidate_set = set(candidate_files)
    already_read = {str(item.get("file")) for item in seen_excerpts}
    new_excerpts: list[dict[str, object]] = []
    search_notes: list[str] = []
    spent_bytes = 0

    for step in range(max_steps):
        remaining_steps = max_steps - step
        context = _explore_context(
            task=task,
            candidate_files=candidate_files,
            already_read=already_read,
            search_notes=search_notes,
            remaining_steps=remaining_steps,
            remaining_bytes=max_bytes - spent_bytes,
        )
        try:
            decision = await decider(context)
        except Exception as exc:  # noqa: BLE001 - exploration is best-effort
            logger.warning(f"project explore decision failed: {exc}")
            break

        if decision.action == "done":
            break

        target = decision.target.strip()
        if not target:
            continue

        if decision.action == "read_file":
            if (
                target not in candidate_set
                or target in already_read
                or Path(target).suffix.casefold() not in _EXPLORE_SUFFIXES
            ):
                # Skip hallucinated paths, repeats, and non-text files.
                already_read.add(target)
                continue
            try:
                content = await tools.read_file(target)
            except Exception:  # noqa: BLE001 - skip unreadable files
                already_read.add(target)
                continue
            excerpt = content[:max_chars_per_file]
            spent_bytes += len(excerpt)
            already_read.add(target)
            new_excerpts.append(
                {
                    "file": target,
                    "content": excerpt,
                    "truncated": len(content) > max_chars_per_file,
                }
            )
            if spent_bytes >= max_bytes:
                break
        elif decision.action == "search_text":
            try:
                matches = await tools.search_text(target, max_matches=20)
            except Exception:  # noqa: BLE001 - skip failed searches
                continue
            files = [
                str(match.get("file"))
                for match in matches
                if isinstance(match, dict) and match.get("file")
            ]
            note = f"search '{target}' -> " + (", ".join(files[:8]) or "no matches")
            search_notes.append(note)

    if new_excerpts:
        logger.info(f"project explore added {len(new_excerpts)} file(s)")
    return new_excerpts


def _explore_context(
    *,
    task: str,
    candidate_files: list[str],
    already_read: set[str],
    search_notes: list[str],
    remaining_steps: int,
    remaining_bytes: int,
) -> str:
    """Build the user message for one exploration decision."""
    available = [f for f in candidate_files if f not in already_read][:60]
    lines = [
        f"TASK:\n{task}",
        "",
        "AVAILABLE FILES (read by exact path):",
        *(f"- {name}" for name in available),
    ]
    if already_read:
        lines.extend(["", "ALREADY READ:", *(f"- {name}" for name in sorted(already_read))])
    if search_notes:
        lines.extend(["", "SEARCH NOTES:", *search_notes])
    lines.extend(
        [
            "",
            f"Budget: {remaining_steps} step(s), ~{remaining_bytes} bytes left.",
            "Pick the single most useful next action, or 'done'.",
        ]
    )
    return "\n".join(lines)


async def _model_explore_decision(context: str) -> ExploreDecision:
    """Ask the local model for the next exploration step."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.llm.pool import Capability, get_pool

    pool = get_pool()
    messages = [
        SystemMessage(content=_EXPLORE_SYSTEM),
        HumanMessage(content=context),
    ]
    return await pool.astructured(
        messages,
        capability=Capability.REASONER,
        schema=ExploreDecision,
        temperature=0.1,
    )
