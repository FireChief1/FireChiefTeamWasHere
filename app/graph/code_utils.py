"""Small code-shaping helpers shared by graph nodes."""

from __future__ import annotations


def strip_code_fences(text: str) -> str:
    """Remove a wrapping markdown code fence from LLM output, if present."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return text
    lines = stripped.splitlines()[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)
