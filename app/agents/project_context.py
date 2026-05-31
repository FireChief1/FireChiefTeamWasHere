"""Prompt helpers for project-level repository context."""

from __future__ import annotations

from app.graph.state import AgentState


def project_context_section(state: AgentState) -> str:
    """Return a compact repository context section for project-mode prompts."""
    if state.get("mode") != "project":
        return ""

    parts: list[str] = []
    profile = state.get("task_profile")
    if profile:
        parts.append(f"TASK PROFILE:\n{profile}")
    if profile == "static_web":
        parts.append(
            "OUTPUT RULE:\n"
            "Create static HTML/CSS/JavaScript artifacts for the selected "
            "project folder, such as index.html. Repository files listed below "
            "are context only; do not modify this agent system's Python files "
            "or documentation unless the user explicitly asks for that."
        )
    if state.get("project_summary"):
        parts.append(f"SUMMARY:\n{state['project_summary']}")
    if state.get("project_memory"):
        parts.append(f"PROJECT MEMORY:\n{state['project_memory']}")
    if state.get("project_vision_context"):
        parts.append(
            "ATTACHED IMAGE ANALYSIS -- use as user-provided visual context; "
            "do not claim you inspected the image yourself again:\n"
            + str(state["project_vision_context"])
        )
    if state.get("project_brief"):
        lines = [str(state["project_brief"])]
        stack = state.get("project_stack") or []
        if stack:
            lines.append("Stack: " + ", ".join(stack[:8]))
        entrypoints = state.get("project_entrypoints") or []
        if entrypoints:
            lines.append("Entrypoints: " + ", ".join(entrypoints[:6]))
        test_commands = state.get("project_test_commands") or []
        if test_commands:
            lines.append("Test commands: " + ", ".join(test_commands[:6]))
        risks = state.get("project_risks") or []
        if risks:
            lines.append("Risks: " + " | ".join(risks[:5]))
        parts.append("PROJECT BRIEF:\n" + "\n".join(lines))

    edit_targets = state.get("project_edit_targets") or []
    if edit_targets:
        lines = []
        for target in edit_targets[:3]:
            filename = target.get("file")
            content = target.get("content")
            if not filename or not isinstance(content, str):
                continue
            suffix = "\n[truncated]" if target.get("truncated") else ""
            lines.append(f"# {filename}\n{content}{suffix}")
        if lines:
            parts.append(
                "FILES TO EDIT -- this is the CURRENT full content of the "
                "file(s) the task asks to change. Return the COMPLETE updated "
                "file for each (same filename), preserving everything you are "
                "not explicitly changing. Do not shorten or drop unrelated "
                "code. CRITICAL: keep all existing text, headings, links, and "
                "the page's SUBJECT exactly as they are. If the task is about "
                "design, style, layout, or 'making it modern', change only the "
                "CSS, classes, and markup structure -- never the wording, the "
                "topic, or invent new placeholder content:\n" + "\n\n".join(lines)
            )

    excerpts = state.get("project_file_excerpts") or []
    if excerpts:
        lines = []
        for excerpt in excerpts[:6]:
            filename = excerpt.get("file")
            content = excerpt.get("content")
            truncated = excerpt.get("truncated")
            if not filename or not isinstance(content, str):
                continue
            suffix = "\n[truncated]" if truncated else ""
            lines.append(f"# {filename}\n{content}{suffix}")
        if lines:
            parts.append(
                "RELEVANT FILE EXCERPTS -- preserve existing intent, names, "
                "and subject matter unless the user explicitly asks to replace "
                "them:\n" + "\n\n".join(lines)
            )

    relevant_files = state.get("project_relevant_files") or []
    if relevant_files:
        parts.append(
            "RELEVANT FILES:\n"
            + "\n".join(f"- {filename}" for filename in relevant_files)
        )

    matches = state.get("project_search_matches") or []
    if matches:
        lines = []
        for match in matches[:10]:
            filename = match.get("file")
            line = match.get("line")
            text = match.get("text")
            if filename and line and text:
                lines.append(f"- {filename}:{line}: {text}")
        if lines:
            parts.append("TASK-RELATED SEARCH MATCHES:\n" + "\n".join(lines))

    git_status = (state.get("project_git_status") or "").strip()
    if git_status:
        parts.append(f"GIT STATUS:\n{git_status}")

    git_diff = (state.get("project_git_diff") or "").strip()
    if git_diff:
        parts.append(f"GIT DIFF STAT:\n{git_diff}")

    if not parts:
        return ""
    return (
        "PROJECT CONTEXT -- read-only repository facts gathered before "
        "planning:\n"
        + "\n\n".join(parts)
    )
