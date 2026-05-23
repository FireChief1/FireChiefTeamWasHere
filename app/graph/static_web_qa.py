"""Deterministic QA checks for static web artifacts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.graph.state import AgentState, FeedbackItem, TestResults


def static_web_qa_update(state: AgentState) -> dict[str, Any]:
    """Run deterministic static-web validation instead of pytest."""
    code = state.get("code") or {}
    failures: list[str] = []
    passes: list[str] = []

    html_files = {
        filename: content
        for filename, content in code.items()
        if filename.casefold().endswith(".html")
    }
    record_check(
        bool(html_files),
        "At least one HTML file is present.",
        passes,
        failures,
    )

    combined_html = "\n".join(html_files.values()).casefold()
    record_check(
        "<title" in combined_html,
        "HTML includes a document title.",
        passes,
        failures,
    )
    record_check(
        "<h1" in combined_html,
        "HTML includes a primary heading.",
        passes,
        failures,
    )
    record_check(
        "<body" in combined_html and "</body>" in combined_html,
        "HTML includes a complete body.",
        passes,
        failures,
    )

    broken_refs = broken_local_asset_refs(code, state.get("project_path") or "")
    record_check(
        not broken_refs,
        "Local asset references resolve within generated or existing files.",
        passes,
        failures,
        failure_detail=(
            "Broken local asset reference(s): " + ", ".join(broken_refs)
            if broken_refs
            else ""
        ),
    )

    results = TestResults(
        passed=len(passes),
        failed=len(failures),
        total=len(passes) + len(failures),
        output="\n".join([*passes, *failures]),
    )
    update: dict[str, Any] = {
        "test_results": results,
        "test_code": "Static web validation ran without pytest.",
        "test_cases": [*passes, *failures],
    }
    if failures:
        feedback = list(state.get("review_feedback") or [])
        feedback.append(
            FeedbackItem(
                severity="BLOCKER",
                issue="Static web validation failed:\n" + "\n".join(failures),
                suggestion="Fix the generated HTML/CSS/JS artifacts and broken references.",
            )
        )
        update["review_feedback"] = feedback
    return update


def record_check(
    condition: bool,
    message: str,
    passes: list[str],
    failures: list[str],
    *,
    failure_detail: str = "",
) -> None:
    """Record a deterministic QA check result."""
    if condition:
        passes.append(f"PASS: {message}")
    else:
        failures.append(f"FAIL: {failure_detail or message}")


def broken_local_asset_refs(code: dict[str, str], project_path: str) -> list[str]:
    """Return local href/src references that are missing."""
    generated = set(code)
    root = Path(project_path).expanduser().resolve() if project_path else None
    broken: list[str] = []
    for filename, content in code.items():
        if not filename.casefold().endswith(".html"):
            continue
        base = Path(filename).parent
        for ref in re.findall(r"""(?:href|src)=["']([^"']+)["']""", content, re.IGNORECASE):
            if external_or_anchor_ref(ref):
                continue
            ref_candidate = base / ref
            if ref_candidate.is_absolute() or ".." in ref_candidate.parts:
                broken.append(f"{filename} -> {ref} (escapes project folder)")
                continue
            ref_path = str(ref_candidate.as_posix())
            if ref_path in generated:
                continue
            if root is not None:
                existing = (root / ref_path).resolve()
                if existing.is_relative_to(root) and existing.exists():
                    continue
                if not existing.is_relative_to(root):
                    broken.append(f"{filename} -> {ref} (escapes project folder)")
                    continue
            broken.append(f"{filename} -> {ref}")
    return broken


def external_or_anchor_ref(ref: str) -> bool:
    """Return True for refs static validation should not resolve locally."""
    lowered = ref.casefold()
    return (
        lowered.startswith(("http://", "https://", "mailto:", "tel:", "data:", "//"))
        or lowered.startswith("#")
        or lowered == ""
    )
