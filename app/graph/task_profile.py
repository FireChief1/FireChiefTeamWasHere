"""Deterministic task-profile classification for workflow routing."""

from __future__ import annotations

import re

from app.graph.state import AgentState, TaskProfile

_STATIC_WEB_TERMS = (
    "html",
    "css",
    "javascript",
    "js",
    "web page",
    "webpage",
    "website",
    "site",
    "landing",
    "sayfa",
    "sayfası",
    "sayfasi",
    "web sitesi",
)
_DOCS_TERMS = (
    "readme",
    "doküman",
    "dokuman",
    "documentation",
    "markdown",
    "docs",
)
_PROJECT_TERMS = (
    "analyze",
    "analyse",
    "analiz",
    "degerlendir",
    "değerlendir",
    "gozden",
    "gözden",
    "incele",
    "kontrol",
    "ogren",
    "öğren",
    "refactor",
    "improvement",
    "iyileştirme",
    "iyilestirme",
    "mimari",
    "architecture",
    "öner",
    "oner",
    "propose",
    "proposal",
    "project",
    "proje",
    "projede",
    "projeye",
    "projeyi",
    "workflow",
    "project mode",
    "proje modu",
)
_IMPLEMENTATION_TERMS = (
    "add",
    "build",
    "create",
    "degistir",
    "değiştir",
    "duzenle",
    "düzenle",
    "duzelt",
    "düzelt",
    "ekle",
    "fix",
    "generate",
    "guncelle",
    "güncelle",
    "implement",
    "olustur",
    "oluştur",
    "tasarla",
    "update",
    "uygula",
    "write",
    "yaz",
)
_PYTHON_ARTIFACT_TERMS = (
    ".py",
    "class",
    "def",
    "fonksiyon",
    "function",
    "module",
    "modul",
    "modül",
    "python",
    "pyhton",
    "pyton",
    "pytoon",
    "script",
    "sinif",
    "sınıf",
)
_TURKISH_ASCII_TRANSLATION = str.maketrans(
    {
        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "ö": "o",
        "ş": "s",
        "ü": "u",
    }
)


def classify_task_profile(state: AgentState) -> tuple[TaskProfile, str]:
    """Classify a task into the implementation profile used downstream."""
    task = _normalized_task(state.get("task", ""))
    is_project_mode = state.get("mode") == "project"
    chat_intent = str(state.get("project_chat_intent") or "")
    chat_action = str(state.get("project_chat_action") or "")
    has_static_web_signal = _has_any_term(task, _STATIC_WEB_TERMS)
    has_docs_signal = _has_any_term(task, _DOCS_TERMS)
    has_project_signal = _has_any_term(task, _PROJECT_TERMS)
    has_workflow_implementation_signal = (
        chat_intent == "implementation" or chat_action == "modify_project"
    )
    has_implementation_signal = (
        _has_any_term(task, _IMPLEMENTATION_TERMS)
        or has_workflow_implementation_signal
    )
    has_python_artifact_signal = _has_any_term(task, _PYTHON_ARTIFACT_TERMS)

    if is_project_mode and has_project_signal and not has_implementation_signal:
        return (
            "project",
            (
                "Project Mode task asks for analysis, review, or proposal, so "
                "it uses safe project advisory output."
            ),
        )

    if has_static_web_signal:
        return (
            "static_web",
            "Task mentions static web/page concepts such as HTML, CSS, site, or sayfa.",
        )
    if has_docs_signal:
        return "docs", "Task is primarily documentation-oriented."
    if has_python_artifact_signal and has_implementation_signal:
        if has_workflow_implementation_signal:
            return (
                "python",
                (
                    "Project Chat routed this as implementation and the task "
                    "mentions a Python/code artifact."
                ),
            )
        return "python", "Task explicitly asks for a Python/code artifact."
    if is_project_mode and has_python_artifact_signal and not has_project_signal:
        return (
            "python",
            (
                "Project Mode task mentions a Python/code artifact, so it "
                "uses the Python implementation profile."
            ),
        )
    if is_project_mode and has_project_signal:
        return "project", "Project Mode task targets existing project architecture or workflow."
    if is_project_mode and not has_implementation_signal:
        return (
            "project",
            (
                "Project Mode fallback keeps ambiguous chat or advisory text "
                "out of the Python code-generation profile."
            ),
        )
    return "python", "Default profile for code-generation tasks is Python."


def _normalized_task(task: str) -> str:
    """Normalize task text for profile matching without semantic routing."""
    return " ".join(
        task.casefold().translate(_TURKISH_ASCII_TRANSLATION).strip().split()
    )


def _has_any_term(normalized_task: str, terms: tuple[str, ...]) -> bool:
    """Match terms on word boundaries so `ogrenci` does not trigger `ogren`."""
    for raw_term in terms:
        term = _normalized_task(raw_term)
        if not term:
            continue
        if not term.replace(" ", "").isalnum():
            if term in normalized_task:
                return True
            continue
        if " " in term:
            if term in normalized_task:
                return True
            continue
        pattern = rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])"
        if re.search(pattern, normalized_task):
            return True
    return False
