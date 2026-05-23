"""Deterministic task-profile classification for workflow routing."""

from __future__ import annotations

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


def classify_task_profile(state: AgentState) -> tuple[TaskProfile, str]:
    """Classify a task into the implementation profile used downstream."""
    task = state.get("task", "").casefold()
    is_project_mode = state.get("mode") == "project"
    has_static_web_signal = any(term in task for term in _STATIC_WEB_TERMS)
    has_docs_signal = any(term in task for term in _DOCS_TERMS)
    has_project_signal = any(term in task for term in _PROJECT_TERMS)
    has_implementation_signal = any(term in task for term in _IMPLEMENTATION_TERMS)

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
    if is_project_mode and has_project_signal:
        return "project", "Project Mode task targets existing project architecture or workflow."
    return "python", "Default profile for code-generation tasks is Python."
