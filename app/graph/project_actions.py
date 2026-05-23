"""Project Chat action schema, registry, policy checks, and executors."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, Field

ProjectActionName = Literal[
    "direct_chat",
    "project_status",
    "path_info",
    "list_folder",
    "read_file",
    "analyze_project",
    "modify_project",
    "clarify",
]
ProjectActionRouteSource = Literal["policy", "model", "fallback"]
ProjectActionSafetyStatus = Literal["allowed", "blocked"]

_MAX_READ_BYTES = 200_000
_READABLE_EXTENSIONS = {
    ".css",
    ".htm",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".txt",
    ".ts",
    ".tsx",
}


class ProjectActionDecision(BaseModel):
    """Concrete action selected for a Project Chat message."""

    action: ProjectActionName = Field(
        description="The concrete action the product should execute."
    )
    target: str = Field(
        default="",
        description="Optional project-relative target file/folder path.",
    )
    requires_workflow: bool = Field(
        description="True when the LangGraph Developer/Reviewer/QA workflow is needed."
    )
    read_only: bool = Field(
        default=True,
        description="Whether the action is guaranteed not to write project files.",
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: str = ""
    routed_by: ProjectActionRouteSource = "model"
    safety_status: ProjectActionSafetyStatus = "allowed"
    safety_message: str = ""


class ProjectActionHandler(Protocol):
    """Registered behavior for one concrete Project Chat action."""

    name: ProjectActionName
    read_only: bool

    def validate(
        self,
        action: ProjectActionDecision,
        root: Path,
    ) -> ProjectActionDecision:
        """Validate action-specific safety constraints."""

    def execute(
        self,
        action: ProjectActionDecision,
        message: str,
        root: Path,
    ) -> str | None:
        """Execute the action after validation."""


def normalize_project_message(message: str) -> str:
    """Normalize casual Turkish/English text for policy checks."""
    normalized = message.casefold().translate(
        str.maketrans(
            {
                "ç": "c",
                "ğ": "g",
                "ı": "i",
                "ö": "o",
                "ş": "s",
                "ü": "u",
            }
        )
    )
    return " ".join(normalized.strip().split())


def detect_read_only_project_action(
    message: str,
    project_path: str,
) -> ProjectActionDecision | None:
    """Detect high-confidence read-only actions before the model router."""
    text = normalize_project_message(message)
    if not text:
        return None

    if _looks_like_path_info(text):
        return ProjectActionDecision(
            action="path_info",
            target=_infer_path_target(message, project_path),
            requires_workflow=False,
            read_only=True,
            confidence=0.98,
            reason="Read-only request for a project file or folder path.",
            routed_by="policy",
        )

    if _looks_like_file_inspection(text, project_path):
        target = _infer_file_target(message, project_path)
        return ProjectActionDecision(
            action="read_file",
            target=target,
            requires_workflow=False,
            read_only=True,
            confidence=0.98,
            reason="Read-only request to inspect or summarize a selected project file.",
            routed_by="policy",
        )

    if _looks_like_folder_listing(text):
        return ProjectActionDecision(
            action="list_folder",
            target=".",
            requires_workflow=False,
            read_only=True,
            confidence=0.98,
            reason="Read-only request to list the selected folder contents.",
            routed_by="policy",
        )

    return None


def action_from_chat_decision(
    *,
    message: str,
    intent: str,
    should_run_workflow: bool,
    confidence: float,
    reason: str,
    routed_by: str,
    project_path: str,
) -> ProjectActionDecision:
    """Convert a router intent into a concrete product action."""
    route_source: ProjectActionRouteSource = (
        routed_by if routed_by in {"policy", "model", "fallback"} else "fallback"
    )
    target = ""
    action: ProjectActionName
    read_only = True

    if intent == "folder_listing":
        action = "list_folder"
        target = "."
    elif intent == "file_inspection":
        action = "read_file"
        target = _infer_file_target(message, project_path)
    elif intent == "path_info":
        action = "path_info"
        target = _infer_path_target(message, project_path)
    elif intent == "status":
        action = "project_status"
    elif intent in {"conversation", "help"}:
        action = "direct_chat"
    elif intent == "project_analysis":
        action = "analyze_project"
        read_only = False
    elif intent == "implementation":
        action = "modify_project"
        read_only = False
    else:
        action = "clarify"

    return validate_project_action(
        ProjectActionDecision(
            action=action,
            target=target,
            requires_workflow=should_run_workflow,
            read_only=read_only,
            confidence=confidence,
            reason=reason,
            routed_by=route_source,
        ),
        project_path,
    )


def validate_project_action(
    action: ProjectActionDecision,
    project_path: str,
) -> ProjectActionDecision:
    """Apply deterministic safety checks to a proposed project action."""
    handler = get_project_action_handler(action.action)
    if action.requires_workflow or handler is None:
        return action

    root_or_error = _project_root_or_error(project_path)
    if isinstance(root_or_error, str):
        return _blocked(action, root_or_error)
    return handler.validate(action, root_or_error)


def execute_read_only_project_action(
    action: ProjectActionDecision,
    message: str,
    project_path: str,
) -> str | None:
    """Execute supported read-only actions, returning a user-facing response."""
    validated = validate_project_action(action, project_path)
    if validated.safety_status == "blocked":
        return validated.safety_message

    handler = get_project_action_handler(validated.action)
    if handler is None or not handler.read_only:
        return None

    root_or_error = _project_root_or_error(project_path)
    if isinstance(root_or_error, str):
        return root_or_error
    return handler.execute(validated, message, root_or_error)


def get_project_action_handler(
    action_name: str,
) -> ProjectActionHandler | None:
    """Return the registered handler for an action name."""
    if action_name not in _PROJECT_ACTION_REGISTRY:
        return None
    return _PROJECT_ACTION_REGISTRY[action_name]  # type: ignore[index]


def registered_project_actions() -> tuple[ProjectActionName, ...]:
    """Return registered executable Project Chat action names."""
    return tuple(_PROJECT_ACTION_REGISTRY)


class _ListFolderAction:
    name: ProjectActionName = "list_folder"
    read_only = True

    def validate(
        self,
        action: ProjectActionDecision,
        root: Path,
    ) -> ProjectActionDecision:
        target = _safe_target(root, action.target or ".")
        if target is None or not target.is_dir():
            return _blocked(action, "Requested folder is outside the project or missing.")
        return action

    def execute(
        self,
        action: ProjectActionDecision,
        message: str,
        root: Path,
    ) -> str | None:
        del message
        target = _safe_target(root, action.target or ".")
        if target is None or not target.is_dir():
            return "Requested folder is outside the project or missing."
        return _compose_folder_listing_response(target)


class _ReadFileAction:
    name: ProjectActionName = "read_file"
    read_only = True

    def validate(
        self,
        action: ProjectActionDecision,
        root: Path,
    ) -> ProjectActionDecision:
        if not action.target:
            return action

        target = _safe_target(root, action.target)
        if target is None or not target.is_file():
            return _blocked(action, "Requested file is outside the project or missing.")

        validation_error = _readable_file_validation_error(target)
        if validation_error is not None:
            return _blocked(action, validation_error)
        return action

    def execute(
        self,
        action: ProjectActionDecision,
        message: str,
        root: Path,
    ) -> str | None:
        return _compose_file_inspection_response(message, root, action.target)


class _PathInfoAction:
    name: ProjectActionName = "path_info"
    read_only = True

    def validate(
        self,
        action: ProjectActionDecision,
        root: Path,
    ) -> ProjectActionDecision:
        if not action.target:
            return action

        target = _safe_target(root, action.target)
        if target is None or not target.exists():
            return _blocked(action, "Requested path is outside the project or missing.")
        return action

    def execute(
        self,
        action: ProjectActionDecision,
        message: str,
        root: Path,
    ) -> str | None:
        return _compose_path_info_response(message, root, action.target)


_PROJECT_ACTION_REGISTRY: dict[ProjectActionName, ProjectActionHandler] = {
    "path_info": _PathInfoAction(),
    "list_folder": _ListFolderAction(),
    "read_file": _ReadFileAction(),
}


def _looks_like_path_info(text: str) -> bool:
    if _has_change_terms(text):
        return False

    path_terms = (
        "path",
        "filepath",
        "file path",
        "konum",
        "nerede",
        "yol",
        "yolu",
        "yolunu",
    )
    target_terms = (
        "dosya",
        "dosyasi",
        "file",
        "folder",
        "html",
        "index",
        "klasor",
        "project",
        "proje",
        "readme",
        "repo",
    )
    return any(term in text for term in path_terms) and any(
        term in text for term in target_terms
    )


def _looks_like_folder_listing(text: str) -> bool:
    words = set(text.split())
    if _has_change_terms(text):
        return False

    file_terms = ("dosya", "file", "files")
    folder_terms = ("klasor", "folder", "directory", "dizin", "repo")
    list_terms = ("var", "liste", "list", "goster", "show", "neler", "hangi")
    has_list_signal = any(term in text for term in list_terms) or "ls" in words
    has_target = any(term in text for term in file_terms + folder_terms)
    if has_target and has_list_signal:
        return True
    return any(term in text for term in folder_terms) and (
        "ne var" in text or "neler var" in text
    )


def _looks_like_file_inspection(text: str, project_path: str) -> bool:
    if _has_change_terms(text):
        return False

    inspection_terms = (
        "ac",
        "anlat",
        "icerik",
        "icerigi",
        "oku",
        "konu",
        "nedir",
        "ozet",
        "summary",
        "read",
        "open",
        "content",
        "explain",
    )
    file_terms = (
        "dosya",
        "dosyasi",
        "file",
        "html",
        "index",
        ".html",
        ".md",
        ".txt",
        "readme",
    )
    if any(term in text for term in file_terms) and any(
        term in text for term in inspection_terms
    ):
        return True

    if any(term in text for term in ("icerigi", "icerik", "anlat", "oku", "ozet")):
        return _single_readable_file(project_path) is not None
    return False


def _has_change_terms(text: str) -> bool:
    return any(
        term in text
        for term in (
            "guncelle",
            "duzelt",
            "degistir",
            "sil",
            "olustur",
            "yaz",
            "ekle",
            "commit",
            "push",
        )
    )


def _project_root_or_error(project_path: str) -> Path | str:
    if not project_path:
        return "No project folder is selected."

    root = Path(project_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return f"Project folder is unavailable: {root}"
    return root


def _compose_folder_listing_response(root: Path | None) -> str:
    if root is None:
        return "Önce bir proje klasörü seçmelisin; sonra klasör içeriğini listeleyebilirim."

    try:
        children = [child for child in root.iterdir() if not child.name.startswith(".")]
    except OSError as exc:
        return f"Klasör okunamadı: `{root}`\n\nHata: {exc}"

    if not children:
        return f"`{root}` klasörü boş görünüyor."

    children.sort(key=lambda child: (not child.is_dir(), child.name.casefold()))
    visible = children[:80]
    lines = [f"`{root}` klasöründe gördüklerim:"]
    for child in visible:
        suffix = "/" if child.is_dir() else ""
        lines.append(f"- `{child.name}{suffix}`")
    if len(children) > len(visible):
        lines.append(f"- ... {len(children) - len(visible)} öğe daha")
    lines.append(f"\nToplam: {len(children)} öğe.")
    return "\n".join(lines)


def _compose_file_inspection_response(
    message: str,
    root: Path | None,
    target: str,
) -> str:
    if root is None:
        return "Önce bir proje klasörü seçmelisin; sonra dosya içeriğini okuyabilirim."

    file_path = (
        _safe_target(root, target)
        if target
        else _select_file_for_inspection(message, root)
    )
    if file_path is None:
        readable = _readable_files(root)
        if not readable:
            return f"`{root}` altında okuyabileceğim metin tabanlı dosya bulamadım."
        names = ", ".join(f"`{path.relative_to(root)}`" for path in readable[:8])
        return (
            "Hangi dosyayı okumamı istediğini netleştirir misin? "
            f"Okuyabileceğim bazı dosyalar: {names}."
        )

    validation_error = _readable_file_validation_error(file_path)
    if validation_error is not None:
        return validation_error

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"`{file_path.relative_to(root)}` dosyasını okuyamadım: {exc}"

    relative = file_path.relative_to(root)
    if file_path.suffix.casefold() in {".html", ".htm"}:
        return _summarize_html_file(relative, content)
    return _summarize_text_file(relative, content)


def _compose_path_info_response(message: str, root: Path, target: str) -> str:
    path = _safe_target(root, target) if target else _select_path_for_info(message, root)
    if path is None:
        readable = _readable_files(root)
        if readable:
            names = ", ".join(f"`{item.relative_to(root)}`" for item in readable[:8])
            return (
                f"Proje klasörü: `{root}`\n\n"
                "Hangi dosyanın yolunu istediğini netleştirir misin? "
                f"Okuyabileceğim bazı dosyalar: {names}."
            )
        return f"Proje klasörü: `{root}`"

    relative = "." if path == root else str(path.relative_to(root))
    label = "Proje klasörü" if path == root else ("Klasör yolu" if path.is_dir() else "Dosya yolu")
    lines = [f"{label}: `{path}`"]
    if relative != ".":
        lines.append(f"Proje içi yol: `{relative}`")
    return "\n\n".join(lines)


def _infer_path_target(message: str, project_path: str) -> str:
    if not project_path:
        return ""

    root = Path(project_path).expanduser().resolve()
    selected = _select_path_for_info(message, root)
    if selected is None:
        return ""
    return "." if selected == root else str(selected.relative_to(root))


def _infer_file_target(message: str, project_path: str) -> str:
    if not project_path:
        return ""
    root = Path(project_path).expanduser().resolve()
    target = _select_file_for_inspection(message, root)
    if target is None:
        return ""
    return str(target.relative_to(root))


def _select_path_for_info(message: str, root: Path) -> Path | None:
    text = normalize_project_message(message)
    file_signal = any(
        term in text
        for term in ("dosya", "dosyasi", "file", "html", "index", "readme")
    )
    project_signal = any(term in text for term in ("proje", "project", "repo"))
    folder_signal = any(term in text for term in ("klasor", "folder", "dizin"))

    if project_signal and not file_signal:
        return root

    if folder_signal and not file_signal:
        return root

    target = _select_file_for_inspection(message, root)
    if target is not None:
        return target

    if project_signal or folder_signal:
        return root
    return None


def _select_file_for_inspection(message: str, root: Path) -> Path | None:
    files = _readable_files(root)
    if not files:
        return None

    text = normalize_project_message(message)
    for path in files:
        normalized_name = normalize_project_message(path.name)
        normalized_relative = normalize_project_message(str(path.relative_to(root)))
        if normalized_name in text or normalized_relative in text:
            return path

    if "html" in text:
        html_files = [
            path for path in files if path.suffix.casefold() in {".html", ".htm"}
        ]
        if len(html_files) == 1:
            return html_files[0]
        index_html = [
            path for path in html_files if path.name.casefold() == "index.html"
        ]
        if index_html:
            return index_html[0]

    if "readme" in text:
        readmes = [path for path in files if path.name.casefold().startswith("readme")]
        if len(readmes) == 1:
            return readmes[0]

    if len(files) == 1:
        return files[0]
    return None


def _readable_files(root: Path) -> list[Path]:
    if not root.exists() or not root.is_dir():
        return []

    files: list[Path] = []
    for path in root.rglob("*"):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        if not path.is_file():
            continue
        if path.suffix.casefold() not in _READABLE_EXTENSIONS:
            continue
        files.append(path)
        if len(files) >= 200:
            break
    return sorted(files, key=lambda item: (len(item.parts), str(item).casefold()))


def _single_readable_file(project_path: str) -> Path | None:
    if not project_path:
        return None
    files = _readable_files(Path(project_path).expanduser().resolve())
    return files[0] if len(files) == 1 else None


def _safe_target(root: Path, target: str) -> Path | None:
    candidate = (root / target).expanduser().resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _readable_file_validation_error(path: Path) -> str | None:
    if not path.is_file():
        return "Requested file is outside the project or missing."
    if path.suffix.casefold() not in _READABLE_EXTENSIONS:
        return f"File type is not readable: {path.suffix}"
    try:
        file_size = path.stat().st_size
    except OSError as exc:
        return f"File metadata could not be read safely: {exc}"
    if file_size > _MAX_READ_BYTES:
        return f"File is too large to read safely ({file_size} bytes)."
    return None


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.current_tag = ""
        self.title: list[str] = []
        self.headings: list[str] = []
        self.paragraphs: list[str] = []
        self.list_items: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        self.current_tag = tag.casefold()

    def handle_endtag(self, tag: str) -> None:
        if self.current_tag == tag.casefold():
            self.current_tag = ""

    def handle_data(self, data: str) -> None:
        clean = " ".join(data.split())
        if not clean:
            return
        if self.current_tag == "title":
            self.title.append(clean)
        elif self.current_tag in {"h1", "h2", "h3"}:
            self.headings.append(clean)
        elif self.current_tag == "p":
            self.paragraphs.append(clean)
        elif self.current_tag == "li":
            self.list_items.append(clean)


def _summarize_html_file(relative: Path, content: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(content)
    title = " ".join(parser.title).strip()
    headings = _unique(parser.headings)[:5]
    paragraphs = _unique(parser.paragraphs)[:4]
    list_items = _unique(parser.list_items)[:6]
    topic = title or (headings[0] if headings else "")

    lines = [f"`{relative}` dosyasını okudum."]
    if topic:
        lines.append(f"\nKonu/başlık: **{topic}**")
    if headings:
        lines.append("\nBaşlıklar:")
        lines.extend(f"- {heading}" for heading in headings)
    if paragraphs:
        lines.append("\nAna metin:")
        lines.extend(f"- {paragraph}" for paragraph in paragraphs)
    if list_items:
        lines.append("\nListe öğeleri:")
        lines.extend(f"- {item}" for item in list_items)
    if not any((topic, headings, paragraphs, list_items)):
        lines.append("\nDosya HTML yapısı içeriyor ama okunabilir metin bulamadım.")
    return "\n".join(lines)


def _summarize_text_file(relative: Path, content: str) -> str:
    clean = re.sub(r"\n{3,}", "\n\n", content.strip())
    excerpt = clean[:1600]
    if len(clean) > len(excerpt):
        excerpt += "\n..."
    return f"`{relative}` dosyasını okudum. İlk içerik:\n\n```text\n{excerpt}\n```"


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _blocked(
    action: ProjectActionDecision,
    message: str,
) -> ProjectActionDecision:
    return action.model_copy(
        update={
            "safety_status": "blocked",
            "safety_message": message,
            "requires_workflow": False,
            "read_only": True,
        }
    )
