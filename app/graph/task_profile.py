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

# Language axis: a canonical language (typically from the LLM chat router) maps
# to an implementation profile. Only existing profiles are mapped today; new
# languages (c, cpp, csharp, standalone node) are added here alongside their
# profile, persona, validation, and QA -- this map is the single extension seam.
_LANGUAGE_TO_PROFILE: dict[str, TaskProfile] = {
    "python": "python",
    "py": "python",
    "html": "static_web",
    "css": "static_web",
    "javascript": "node_js",
    "js": "node_js",
    "typescript": "node_js",
    "ts": "node_js",
    "node": "node_js",
    "nodejs": "node_js",
}


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

    # Language axis (preferred): when the chat router named a target language and
    # the task is an implementation, route by language. This is more robust than
    # keywords for terse/symbol-heavy languages (e.g. "C# sinifi yaz") and is the
    # seam new languages plug into. Falls through to the keyword logic below when
    # the router gave no language or one without a profile yet.
    router_language = _normalized_task(str(state.get("project_chat_language") or ""))
    mapped_profile = _LANGUAGE_TO_PROFILE.get(router_language)
    if mapped_profile is not None and has_implementation_signal:
        # Explicit web signals in the task (html, css, page, site, index.html)
        # are high-precision user intent and outrank a fallible router language
        # guess that points at a non-web profile. Without this, a router
        # mislabel like 'python' on an obvious HTML task routes to the Python
        # profile and the generated HTML is rejected as invalid Python.
        if mapped_profile != "static_web" and has_static_web_signal:
            return (
                "static_web",
                f"Task explicitly references web artifacts (HTML/CSS), so it "
                f"overrides the router language '{router_language}'.",
            )
        return (
            mapped_profile,
            f"Chat router identified target language '{router_language}', "
            f"routed to the {mapped_profile} profile.",
        )

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
