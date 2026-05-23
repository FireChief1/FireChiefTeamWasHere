"""Developer-output validation for artifact profiles."""

from __future__ import annotations

import ast
import re
from pathlib import Path

_STATIC_WEB_SUFFIXES = {".html", ".css", ".js", ".json", ".md", ".txt", ".svg"}
_ADVISORY_SUFFIXES = {".md", ".txt"}


def validate_code_files(code: dict[str, str], profile: str = "python") -> str | None:
    """Return a validation error for Developer output, or None if valid."""
    if not code:
        return "Developer produced no source files."
    if profile == "static_web":
        return validate_static_web_files(code)
    if profile in {"docs", "project"}:
        return validate_advisory_files(code, profile=profile)
    for filename, content in code.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.py", filename):
            return (
                f"Developer produced unsupported filename '{filename}'. "
                "Use a simple Python module name such as bank_account.py."
            )
        if not content.strip():
            return f"Developer produced an empty file: {filename}."
        try:
            ast.parse(content)
        except SyntaxError as exc:
            return f"Developer produced invalid Python in {filename}: {exc}."
    return None


def validate_advisory_files(code: dict[str, str], profile: str) -> str | None:
    """Validate docs/project advisory output."""
    if profile == "project" and set(code) != {"PROJECT_PROPOSAL.md"}:
        return (
            "Project analysis tasks must produce exactly PROJECT_PROPOSAL.md "
            "and must not overwrite source or artifact files."
        )
    for filename, content in code.items():
        if not safe_relative_file_path(filename):
            return (
                f"Developer produced unsafe project filename '{filename}'. "
                "Use a safe relative Markdown or text path."
            )
        suffix = Path(filename).suffix.casefold()
        if suffix not in _ADVISORY_SUFFIXES:
            return (
                f"Developer produced unsupported advisory filename '{filename}'. "
                "Use Markdown or text files for docs/project advisory output."
            )
        if not content.strip():
            return f"Developer produced an empty file: {filename}."
    return None


def validate_static_web_files(code: dict[str, str]) -> str | None:
    """Validate static web artifact output."""
    html_files = 0
    for filename, content in code.items():
        if not safe_relative_file_path(filename):
            return (
                f"Developer produced unsafe project filename '{filename}'. "
                "Use a safe relative path such as index.html or assets/style.css."
            )
        suffix = Path(filename).suffix.casefold()
        if suffix not in _STATIC_WEB_SUFFIXES:
            return (
                f"Developer produced unsupported static-web filename '{filename}'. "
                "Use HTML, CSS, JS, JSON, SVG, Markdown, or text files."
            )
        if not content.strip():
            return f"Developer produced an empty file: {filename}."
        if suffix == ".html":
            html_files += 1
            lowered = content.casefold()
            if "<html" not in lowered or "</html>" not in lowered:
                return f"Developer produced incomplete HTML document: {filename}."
    if html_files == 0:
        return "Static web tasks must produce at least one HTML file."
    return None


def safe_relative_file_path(filename: str) -> bool:
    """Return True when filename is a safe relative project path."""
    path = Path(filename)
    if path.is_absolute() or not filename.strip():
        return False
    return ".." not in path.parts and all(
        part and not part.startswith(".") for part in path.parts
    )
