"""Project Chat action schema, registry, safety checks, and executors."""

from __future__ import annotations

import ast
import re
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

ProjectActionName = Literal[
    "direct_chat",
    "project_status",
    "path_info",
    "list_folder",
    "read_file",
    "current_time",
    "calculate",
    "assistant_capabilities",
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
_MAX_ARITHMETIC_EXPRESSION_LENGTH = 80


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
    """Normalize casual Turkish/English text for safe target resolution."""
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


def action_from_chat_decision(
    *,
    message: str,
    intent: str,
    should_run_workflow: bool,
    confidence: float,
    reason: str,
    routed_by: str,
    project_path: str,
    action_name: str | None = None,
    action_target: str | None = None,
) -> ProjectActionDecision:
    """Convert a router intent into a concrete product action."""
    route_source: ProjectActionRouteSource = (
        routed_by if routed_by in {"policy", "model", "fallback"} else "fallback"
    )
    default_action = _action_for_intent(intent)
    action = _normalize_action_name(action_name) or default_action
    if intent == "help" and action == "direct_chat":
        action = default_action
    if _requires_workflow(action) != should_run_workflow:
        action = default_action
    target = action_target or _target_for_action(action, message, project_path)
    requires_workflow = _requires_workflow(action)
    read_only = not requires_workflow

    return validate_project_action(
        ProjectActionDecision(
            action=action,
            target=target,
            requires_workflow=requires_workflow,
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


class _CurrentTimeAction:
    name: ProjectActionName = "current_time"
    read_only = True

    def validate(
        self,
        action: ProjectActionDecision,
        root: Path,
    ) -> ProjectActionDecision:
        del root
        return action

    def execute(
        self,
        action: ProjectActionDecision,
        message: str,
        root: Path,
    ) -> str | None:
        del action, message, root
        return _compose_current_time_response()


class _CalculateAction:
    name: ProjectActionName = "calculate"
    read_only = True

    def validate(
        self,
        action: ProjectActionDecision,
        root: Path,
    ) -> ProjectActionDecision:
        del root
        if not action.target:
            return action
        if _safe_arithmetic_result(action.target) is None:
            return _blocked(action, "Hesaplanacak ifadeyi güvenli şekilde okuyamadım.")
        return action

    def execute(
        self,
        action: ProjectActionDecision,
        message: str,
        root: Path,
    ) -> str | None:
        del root
        expression = action.target or _extract_arithmetic_expression(message)
        result = _safe_arithmetic_result(expression)
        if result is None:
            return "Hesaplanacak ifadeyi netleştirir misin?"
        return f"`{expression}` sonucu: **{_format_number(result)}**"


class _AssistantCapabilitiesAction:
    name: ProjectActionName = "assistant_capabilities"
    read_only = True

    def validate(
        self,
        action: ProjectActionDecision,
        root: Path,
    ) -> ProjectActionDecision:
        del root
        return action

    def execute(
        self,
        action: ProjectActionDecision,
        message: str,
        root: Path,
    ) -> str | None:
        del action, message, root
        return (
            "Sadece HTML ile sınırlı değilim. Şu an bu projede en güvenli "
            "desteklediğim çıktılar: Python modülleri, statik HTML/CSS/vanilla "
            "JavaScript, Markdown/dokümantasyon ve proje analizi/öneri "
            "çıktıları. Seçili projenin stack'i sadece bağlamdır; benim genel "
            "kapasitemi tek başına sınırlamaz."
        )


_PROJECT_ACTION_REGISTRY: dict[ProjectActionName, ProjectActionHandler] = {
    "path_info": _PathInfoAction(),
    "list_folder": _ListFolderAction(),
    "read_file": _ReadFileAction(),
    "current_time": _CurrentTimeAction(),
    "calculate": _CalculateAction(),
    "assistant_capabilities": _AssistantCapabilitiesAction(),
}


def _normalize_action_name(action_name: str | None) -> ProjectActionName | None:
    allowed: tuple[ProjectActionName, ...] = (
        "direct_chat",
        "project_status",
        "path_info",
        "list_folder",
        "read_file",
        "current_time",
        "calculate",
        "assistant_capabilities",
        "analyze_project",
        "modify_project",
        "clarify",
    )
    if action_name in allowed:
        return action_name  # type: ignore[return-value]
    return None


def _action_for_intent(intent: str) -> ProjectActionName:
    actions_by_intent: dict[str, ProjectActionName] = {
        "folder_listing": "list_folder",
        "file_inspection": "read_file",
        "path_info": "path_info",
        "status": "project_status",
        "conversation": "direct_chat",
        "help": "assistant_capabilities",
        "project_analysis": "analyze_project",
        "implementation": "modify_project",
    }
    return actions_by_intent.get(intent, "clarify")


def _target_for_action(
    action: ProjectActionName,
    message: str,
    project_path: str,
) -> str:
    if action == "list_folder":
        return "."
    if action == "read_file":
        return _infer_file_target(message, project_path)
    if action == "path_info":
        return _infer_path_target(message, project_path)
    if action == "calculate":
        return _extract_arithmetic_expression(message)
    return ""


def _requires_workflow(action: ProjectActionName) -> bool:
    return action in {"analyze_project", "modify_project"}


def _compose_current_time_response(now: datetime | None = None) -> str:
    current = now or datetime.now(ZoneInfo("Europe/Istanbul"))
    return (
        f"Saat şu anda {current:%H:%M} (Europe/Istanbul).\n\n"
        f"Tarih: {current:%d/%m/%Y}."
    )


def can_calculate_message(message: str) -> bool:
    """Return True when a chat message contains a simple arithmetic expression."""
    return bool(_extract_arithmetic_expression(message))


def _extract_arithmetic_expression(message: str) -> str:
    """Extract a bounded arithmetic expression from a natural-language message."""
    token_pattern = r"\d+(?:[.,]\d+)?|[()+\-*/]"
    tokens = re.findall(token_pattern, message)
    number_count = sum(1 for token in tokens if re.search(r"\d", token))
    operator_count = sum(1 for token in tokens if token in {"+", "-", "*", "/"})
    if number_count < 2 or operator_count < 1:
        return ""
    expression = " ".join(token.replace(",", ".") for token in tokens)
    expression = re.sub(r"\s+", " ", expression).strip()
    if len(expression) > _MAX_ARITHMETIC_EXPRESSION_LENGTH:
        return ""
    if _safe_arithmetic_result(expression) is None:
        return ""
    return expression


def _safe_arithmetic_result(expression: str) -> float | None:
    if not expression or len(expression) > _MAX_ARITHMETIC_EXPRESSION_LENGTH:
        return None
    try:
        tree = ast.parse(expression, mode="eval")
        return float(_eval_arithmetic_node(tree.body))
    except (ArithmeticError, SyntaxError, TypeError, ValueError):
        return None


def _eval_arithmetic_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_arithmetic_node(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp):
        left = _eval_arithmetic_node(node.left)
        right = _eval_arithmetic_node(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise ArithmeticError("division by zero")
            return left / right
    raise ValueError("unsupported arithmetic expression")


def _format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.10g}"


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
