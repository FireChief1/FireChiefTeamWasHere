"""Deterministic QA checks for docs/project advisory outputs."""

from __future__ import annotations

import re
from typing import Any

from app.graph.state import AgentState, FeedbackItem, TestResults

_SOURCE_SUFFIXES = (".html", ".css", ".js", ".py")
_GROUNDING_STOPWORDS = {
    "about",
    "index",
    "page",
    "site",
    "static",
    "title",
    "welcome",
}


def advisory_qa_update(state: AgentState) -> dict[str, Any]:
    """Validate markdown/text advisory output without pytest."""
    code = state.get("code") or {}
    failures: list[str] = []
    passes: list[str] = []

    advisory_files = [
        filename
        for filename in code
        if filename.casefold().endswith((".md", ".txt"))
    ]
    source_files = [
        filename
        for filename in code
        if filename.casefold().endswith(_SOURCE_SUFFIXES)
    ]

    _record(
        bool(advisory_files),
        "At least one markdown/text advisory file exists.",
        passes,
        failures,
    )
    _record(
        not source_files,
        "No source/artifact files are modified in advisory mode.",
        passes,
        failures,
    )
    if state.get("task_profile") == "project":
        _record(
            set(code) == {"PROJECT_PROPOSAL.md"},
            "Project advisory output is scoped to PROJECT_PROPOSAL.md.",
            passes,
            failures,
        )

    combined = "\n".join(code.values()).strip()
    _record(
        len(combined) >= 80,
        "Advisory output has enough detail to be useful.",
        passes,
        failures,
    )
    _record(
        any(marker in combined for marker in ("#", "-", "1.")),
        "Advisory output uses readable markdown/list structure.",
        passes,
        failures,
    )
    grounding_terms = project_grounding_terms(state)
    if grounding_terms:
        combined_lower = combined.casefold()
        _record(
            any(term in combined_lower for term in grounding_terms),
            "Advisory output references observed project title or heading terms.",
            passes,
            failures,
        )

    results = TestResults(
        passed=len(passes),
        failed=len(failures),
        total=len(passes) + len(failures),
        output="\n".join([*passes, *failures]),
    )
    update: dict[str, Any] = {
        "test_results": results,
        "test_code": "Project advisory validation ran without pytest.",
        "test_cases": [*passes, *failures],
    }
    if failures:
        feedback = list(state.get("review_feedback") or [])
        feedback.append(
            FeedbackItem(
                severity="BLOCKER",
                issue="Project advisory validation failed:\n" + "\n".join(failures),
                suggestion=(
                    "Return a grounded markdown/text proposal and avoid modifying "
                    "source or artifact files in project advisory mode."
                ),
            )
        )
        update["review_feedback"] = feedback
    return update


def _record(
    condition: bool,
    message: str,
    passes: list[str],
    failures: list[str],
) -> None:
    """Record one advisory QA check."""
    if condition:
        passes.append(f"PASS: {message}")
    else:
        failures.append(f"FAIL: {message}")


def project_grounding_terms(state: AgentState) -> list[str]:
    """Extract title/heading terms that advisory output should acknowledge."""
    if state.get("task_profile") != "project":
        return []

    terms: list[str] = []
    for excerpt in state.get("project_file_excerpts") or []:
        content = excerpt.get("content")
        if not isinstance(content, str):
            continue
        for pattern in (
            r"<title[^>]*>(.*?)</title>",
            r"<h1[^>]*>(.*?)</h1>",
        ):
            for match in re.findall(pattern, content, flags=re.IGNORECASE | re.DOTALL):
                text = re.sub(r"<[^>]+>", " ", match)
                for raw_word in re.findall(r"[\w-]{4,}", text.casefold()):
                    word = raw_word.strip("_-")
                    if word and word not in _GROUNDING_STOPWORDS and word not in terms:
                        terms.append(word)
                    if len(terms) >= 8:
                        return terms
    return terms
