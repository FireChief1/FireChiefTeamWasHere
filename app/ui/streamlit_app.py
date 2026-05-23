"""Streamlit UI for the multi-agent code development system.

A flow-tracking interface: enter a task, watch each agent work in real time,
and inspect exactly what every agent produced -- the plan, the generated code,
the review findings, and the test output.

Run from the project root:

    streamlit run app/ui/streamlit_app.py
"""

from __future__ import annotations

import asyncio
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st
import streamlit.components.v1 as components

from app.config import PROJECT_ROOT
from app.graph.project_chat_intent import (
    ProjectChatContext,
    answer_project_chat_direct,
    format_project_chat_route,
    route_project_chat_intent,
)
from app.graph.project_output import apply_project_files
from app.graph.state import AgentState
from app.graph.task_profile import classify_task_profile
from app.graph.workflow import build_workflow
from app.history import load_history, record_run
from app.llm.pool import build_default_pool, set_pool
from app.project_registry import (
    ProjectCheckpoint,
    ProjectRecord,
    ProjectTimelineEvent,
    delete_project,
    load_project,
    load_project_checkpoints,
    load_project_timeline,
    load_projects,
    open_project,
    project_memory_summary,
    record_project_apply,
    record_project_checkpoint,
    record_project_message,
    rename_project,
)

DEFAULT_TASK = (
    "Write a BankAccount class with deposit and withdraw methods. "
    "Withdraw must reject amounts larger than the balance."
)
DEFAULT_PROJECT_TASK = (
    "Projeye mesaj yaz; analiz veya kod görevi verirsen ajan akışı başlar."
)
RunMode = Literal["generate", "project"]

STAGES: list[tuple[str, str]] = [
    ("project_intake", "Project"),
    ("project_brief", "Brief"),
    ("task_classifier", "Profile"),
    ("rag", "RAG"),
    ("analyst", "Analyst"),
    ("developer", "Developer"),
    ("reviewer", "Reviewer"),
    ("qa", "QA"),
    ("supervisor", "Supervisor"),
    ("integrator", "Integrator"),
]
_LABELS = dict(STAGES)
_ICON = {"done": "✅", "active": "⚡", "wait": "⬜"}
_LOOP_STAGES = ("developer", "reviewer", "qa", "supervisor")
_PENDING_PROJECT_APPLY_KEY = "pending_project_apply"
_PROJECT_APPLY_RESULT_KEY = "project_apply_result"
_PROJECT_REGISTRY_CURRENT_OPTION = "__current__"
_PROJECT_REGISTRY_SUPPRESSED_KEY = "project_registry_suppressed_path"
_FOLDER_SKIP_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "chroma_db",
    "htmlcov",
    "multi_agent_code_team.egg-info",
    "node_modules",
    "workspace",
}
_FOLDER_LIST_LIMIT = 40


@st.cache_data(ttl=10, show_spinner=False)
def _cached_load_projects() -> list[ProjectRecord]:
    """Load sidebar projects through Streamlit's short-lived cache."""
    return load_projects()


@st.cache_data(ttl=10, show_spinner=False)
def _cached_load_project(path: str) -> ProjectRecord | None:
    """Load a selected project through Streamlit's short-lived cache."""
    return load_project(path)


@st.cache_data(ttl=10, show_spinner=False)
def _cached_load_project_checkpoints(
    path: str, limit: int
) -> list[ProjectCheckpoint]:
    """Load project checkpoints through Streamlit's short-lived cache."""
    return load_project_checkpoints(path, limit=limit)


@st.cache_data(ttl=10, show_spinner=False)
def _cached_load_project_timeline(
    path: str, limit: int
) -> list[ProjectTimelineEvent]:
    """Load project timeline through Streamlit's short-lived cache."""
    return load_project_timeline(path, limit=limit)


def _clear_project_registry_cache() -> None:
    """Clear cached project registry reads after registry writes."""
    _cached_load_projects.clear()
    _cached_load_project.clear()
    _cached_load_project_checkpoints.clear()
    _cached_load_project_timeline.clear()


def _valid_directory(path: Path | str, fallback: Path = PROJECT_ROOT) -> Path:
    """Return a resolved directory path, falling back when invalid."""
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        return fallback.resolve()
    return resolved if resolved.exists() and resolved.is_dir() else fallback.resolve()


def _escape_applescript_text(value: str) -> str:
    """Escape a string for use inside an AppleScript quoted literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _choose_folder_with_finder(default_path: Path) -> Path | None:
    """Open the macOS folder picker and return the selected folder."""
    script = (
        'POSIX path of (choose folder with prompt "Proje klasörünü seç" '
        f'default location POSIX file "{_escape_applescript_text(str(default_path))}")'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None
    selected = result.stdout.strip()
    if not selected:
        return None
    return _valid_directory(selected)


def _folder_shortcuts() -> list[tuple[str, Path]]:
    """Return useful starting points for the local folder picker."""
    candidates = [
        ("Bu proje", PROJECT_ROOT),
        ("Desktop", Path.home() / "Desktop"),
        ("Home", Path.home()),
    ]
    seen: set[Path] = set()
    shortcuts: list[tuple[str, Path]] = []
    for label, path in candidates:
        resolved = _valid_directory(path)
        if resolved in seen:
            continue
        seen.add(resolved)
        shortcuts.append((label, resolved))
    return shortcuts


def _child_directories(path: Path) -> list[Path]:
    """List visible child directories for the folder picker."""
    try:
        children = [
            child
            for child in path.iterdir()
            if child.is_dir()
            and not child.name.startswith(".")
            and child.name not in _FOLDER_SKIP_NAMES
        ]
    except OSError:
        return []
    return sorted(children, key=lambda item: item.name.casefold())[:_FOLDER_LIST_LIMIT]


def _shortcut_label(path: Path) -> str:
    """Return a friendly label for a shortcut path."""
    for label, shortcut in _folder_shortcuts():
        if path == shortcut:
            return label
    return path.name or str(path)


def _navigation_label(option: Path | None) -> str:
    """Return the label for a folder navigation option."""
    if option is None:
        return "Alt klasör veya üst klasör seç"
    return option.name or str(option)


def _target_label(path: Path) -> str:
    """Return the label for a selectable target folder."""
    if path == _valid_directory(st.session_state.get("project_picker_current_path", "")):
        return "Bu klasör"
    return path.name or str(path)


def render_project_folder_picker(default_path: Path) -> str:
    """Render a local folder picker and return the selected path."""
    current_key = "project_picker_current_path"
    selected_key = "project_picker_selected_path"
    if current_key not in st.session_state:
        st.session_state[current_key] = str(default_path)
    if selected_key not in st.session_state:
        st.session_state[selected_key] = str(default_path)

    current = _valid_directory(st.session_state[current_key])
    selected = _valid_directory(st.session_state[selected_key])

    st.markdown("**Proje klasörü**")
    st.caption(f"Seçili: `{selected}`")
    if st.button("Finder'dan klasör seç", width="stretch"):
        chosen = _choose_folder_with_finder(selected)
        if chosen is None:
            st.warning("Klasör seçimi iptal edildi veya Finder açılamadı.")
        else:
            st.session_state[current_key] = str(chosen)
            st.session_state[selected_key] = str(chosen)
            st.rerun()

    with st.expander("Uygulama içi gezgin", expanded=False):
        selected = _render_inline_folder_browser(
            current=current,
            selected=selected,
            current_key=current_key,
            selected_key=selected_key,
        )
    return str(selected)


def render_project_registry_selector(projects: list[ProjectRecord]) -> None:
    """Render the registered projects list and update the selected path."""
    st.markdown("**Projeler**")
    if not projects:
        st.caption("Henüz kayıtlı proje yok; seçtiğin klasör burada görünecek.")
        return

    current = str(
        _valid_directory(
            st.session_state.get("project_picker_selected_path", PROJECT_ROOT)
        )
    )
    project_paths = [project["path"] for project in projects]
    options = [_PROJECT_REGISTRY_CURRENT_OPTION, *project_paths]
    index = project_paths.index(current) + 1 if current in project_paths else 0
    choice = st.selectbox(
        "Kayıtlı projeler",
        options,
        index=index,
        format_func=lambda option: _project_option_label(option, projects),
    )
    if choice != _PROJECT_REGISTRY_CURRENT_OPTION and choice != current:
        st.session_state["project_picker_current_path"] = choice
        st.session_state["project_picker_selected_path"] = choice
        st.rerun()


def ensure_project_open(path: str) -> ProjectRecord | None:
    """Open a project once per selected path, then serve it from cache."""
    resolved = str(_valid_directory(path))
    opened_key = "project_registry_opened_path"
    suppressed = st.session_state.get(_PROJECT_REGISTRY_SUPPRESSED_KEY)
    if suppressed and suppressed != resolved:
        st.session_state.pop(_PROJECT_REGISTRY_SUPPRESSED_KEY, None)
    if suppressed == resolved:
        return _cached_load_project(resolved)
    if st.session_state.get(opened_key) != resolved:
        project = open_project(resolved)
        _clear_project_registry_cache()
        st.session_state[opened_key] = resolved
        return project
    project = _cached_load_project(resolved)
    if project is None:
        project = open_project(resolved)
        _clear_project_registry_cache()
        st.session_state[opened_key] = resolved
    return project


def render_project_memory_summary(
    project: ProjectRecord | None,
    checkpoints: list[ProjectCheckpoint],
    timeline: list[ProjectTimelineEvent],
) -> None:
    """Render a compact, refreshable summary of the selected project's memory."""
    if project is None:
        st.warning("Postgres proje kaydı açılamadı.")
        return

    st.markdown("**Açık proje**")
    st.caption(f"`{project['name']}`")
    if project["last_task"]:
        st.caption(f"Son görev: {project['last_task'][:80]}")
    if project["last_status"]:
        st.caption(f"Son durum: `{project['last_status']}`")
    if project["project_stack"]:
        st.caption("Stack: " + ", ".join(project["project_stack"][:5]))
    if project["project_test_commands"]:
        st.caption(
            "Test: " + ", ".join(f"`{cmd}`" for cmd in project["project_test_commands"][:3])
        )
    if checkpoints:
        with st.expander(f"Checkpoint'ler ({len(checkpoints)})", expanded=False):
            for checkpoint in checkpoints[:5]:
                st.caption(
                    f"{checkpoint['created_at']} · {checkpoint['status']} · "
                    f"{checkpoint['task'][:90]}"
                )
    if timeline:
        with st.expander(f"Timeline ({len(timeline)})", expanded=False):
            for event in timeline[:8]:
                st.caption(
                    f"{event['created_at']} · {event['kind']} · "
                    f"{event['title']}"
                )
                if event["body"]:
                    st.caption(event["body"][:120])


def render_project_management_panel(
    project: ProjectRecord | None,
    selected_path: str,
) -> None:
    """Render project registry management actions."""
    if project is None:
        if st.button("Projeyi kayda ekle", key="reopen_project_registry_entry"):
            st.session_state.pop(_PROJECT_REGISTRY_SUPPRESSED_KEY, None)
            open_project(selected_path)
            _clear_project_registry_cache()
            st.rerun()
        return

    with st.expander("Proje yönetimi", expanded=False):
        rename_key = f"project_rename_{project['id']}"
        delete_key = f"project_delete_confirm_{project['id']}"
        new_name = st.text_input("Proje adı", value=project["name"], key=rename_key)
        if st.button("Yeniden adlandır", key=f"rename_button_{project['id']}"):
            renamed = rename_project(project["path"], new_name)
            _clear_project_registry_cache()
            if renamed is None:
                st.error("Proje adı güncellenemedi.")
            else:
                st.success("Proje adı güncellendi.")
                st.rerun()

        st.caption("Silme yalnızca Postgres proje kaydını siler; dosyalara dokunmaz.")
        confirm_delete = st.checkbox(
            "Bu proje kaydını silmeyi onaylıyorum",
            key=delete_key,
        )
        if st.button(
            "Kayıttan sil",
            disabled=not confirm_delete,
            key=f"delete_button_{project['id']}",
        ):
            deleted = delete_project(project["path"])
            _clear_project_registry_cache()
            if deleted:
                st.session_state[_PROJECT_REGISTRY_SUPPRESSED_KEY] = project["path"]
                st.session_state["project_picker_current_path"] = str(PROJECT_ROOT)
                st.session_state["project_picker_selected_path"] = str(PROJECT_ROOT)
                st.session_state.pop("project_registry_opened_path", None)
                st.success("Proje kaydı silindi.")
                st.rerun()
            st.error("Proje kaydı silinemedi.")


def _project_option_label(option: str, projects: list[ProjectRecord]) -> str:
    """Return the label for a registered project select option."""
    if option == _PROJECT_REGISTRY_CURRENT_OPTION:
        return "Mevcut klasör seçimi"
    for project in projects:
        if project["path"] == option:
            return project["name"]
    return option


def _render_inline_folder_browser(
    *,
    current: Path,
    selected: Path,
    current_key: str,
    selected_key: str,
) -> Path:
    """Render the in-app fallback browser and return the selected folder."""
    shortcuts = _folder_shortcuts()
    shortcut_paths = [path for _, path in shortcuts]
    shortcut_index = next(
        (index for index, path in enumerate(shortcut_paths) if path == current),
        None,
    )
    shortcut_choice = st.selectbox(
        "Hızlı konum",
        shortcut_paths,
        index=shortcut_index,
        format_func=_shortcut_label,
        placeholder="Hızlı konum seç",
    )
    if shortcut_choice is not None and shortcut_choice != current:
        st.session_state[current_key] = str(shortcut_choice)
        st.rerun()

    children = _child_directories(current)
    navigation_options: list[Path | None] = [None]
    if current.parent != current:
        navigation_options.append(current.parent)
    navigation_options.extend(children)

    st.caption(f"Gezilen: `{current}`")
    navigation_choice = st.selectbox(
        "Klasöre git",
        navigation_options,
        index=0,
        format_func=_navigation_label,
    )
    if navigation_choice is not None:
        st.session_state[current_key] = str(navigation_choice)
        st.rerun()

    target_options = [current, *children]
    target_index = next(
        (index for index, path in enumerate(target_options) if path == selected),
        0,
    )
    target_choice = st.selectbox(
        "Kullanılacak klasör",
        target_options,
        index=target_index,
        format_func=_target_label,
    )
    selected = _valid_directory(target_choice)
    st.session_state[selected_key] = str(selected)
    st.caption(f"Seçili: `{selected}`")

    if len(children) == _FOLDER_LIST_LIMIT:
        st.caption("İlk 40 klasör gösteriliyor.")
    return selected


def _code_language(filename: str) -> str:
    """Return a Streamlit code-block language for generated files."""
    suffix = Path(filename).suffix.casefold()
    return {
        ".css": "css",
        ".html": "html",
        ".js": "javascript",
        ".json": "json",
        ".md": "markdown",
        ".py": "python",
        ".svg": "xml",
        ".txt": "text",
    }.get(suffix, "text")


def _primary_html_file(code: dict[str, str]) -> tuple[str, str] | None:
    """Return the primary HTML artifact for static preview."""
    html_files = [
        (filename, content)
        for filename, content in code.items()
        if filename.casefold().endswith(".html")
    ]
    if not html_files:
        return None
    for filename, content in html_files:
        if Path(filename).name.casefold() == "index.html":
            return filename, content
    return html_files[0]


def _generated_asset(code: dict[str, str], html_filename: str, ref: str) -> str | None:
    """Return a generated local asset referenced by an HTML file."""
    lowered = ref.casefold()
    if lowered.startswith(("http://", "https://", "mailto:", "tel:", "data:", "#")):
        return None
    ref_path = str((Path(html_filename).parent / ref).as_posix())
    return code.get(ref_path) or code.get(ref.lstrip("./"))


def _html_with_generated_assets(
    code: dict[str, str], html_filename: str, html: str
) -> str:
    """Inline generated CSS/JS references so the preview matches the output."""
    def replace_stylesheet(match: re.Match[str]) -> str:
        href = match.group("href")
        content = _generated_asset(code, html_filename, href)
        if content is None:
            return match.group(0)
        return f"<style>\n{content}\n</style>"

    def replace_script(match: re.Match[str]) -> str:
        src = match.group("src")
        content = _generated_asset(code, html_filename, src)
        if content is None:
            return match.group(0)
        return f"<script>\n{content}\n</script>"

    html = re.sub(
        r"<link\b(?=[^>]*\brel=[\"']stylesheet[\"'])(?=[^>]*\bhref=[\"'](?P<href>[^\"']+)[\"'])[^>]*>",
        replace_stylesheet,
        html,
        flags=re.IGNORECASE,
    )
    return re.sub(
        r"<script\b(?=[^>]*\bsrc=[\"'](?P<src>[^\"']+)[\"'])[^>]*>\s*</script>",
        replace_script,
        html,
        flags=re.IGNORECASE,
    )


def render_static_web_preview(code: dict[str, str]) -> None:
    """Render the generated static HTML in a browser-like preview pane."""
    primary = _primary_html_file(code)
    if primary is None:
        return
    filename, html = primary
    st.markdown(f"**Tarayıcı ön izlemesi:** `{filename}`")
    components.html(
        _html_with_generated_assets(code, filename, html),
        height=460,
        scrolling=True,
    )


def _is_static_validation(test_code: str | None) -> bool:
    """Return True when QA output came from deterministic static validation."""
    return bool(test_code and test_code.startswith("Static web validation"))


def _is_advisory_validation(test_code: str | None) -> bool:
    """Return True when QA output came from deterministic advisory validation."""
    return bool(test_code and test_code.startswith("Project advisory validation"))


def _project_apply_payload(state: dict[str, Any]) -> dict[str, Any] | None:
    """Return the pending Project Mode apply payload for a completed preview."""
    if state.get("mode") != "project":
        return None
    if state.get("status") not in {"SUCCESS", "COMPLETED_WITH_WARNINGS"}:
        return None
    if state.get("project_path_mismatch"):
        return None
    code = state.get("code") or {}
    target_path = state.get("integration_target_path") or state.get("project_path")
    if not code or not target_path or not state.get("integration_preview_only"):
        return None
    return {
        "task_id": state.get("task_id") or uuid.uuid4().hex[:8],
        "target_path": target_path,
        "mcp_root": state.get("project_mcp_root") or "",
        "code": code,
        "planned_files": state.get("integration_planned_files") or list(code),
        "file_actions": state.get("integration_file_actions") or [],
        "diff": state.get("integration_diff") or "",
    }


def _store_pending_project_apply(state: dict[str, Any]) -> None:
    """Persist a pending apply payload across Streamlit reruns."""
    payload = _project_apply_payload(state)
    if payload is not None:
        st.session_state[_PENDING_PROJECT_APPLY_KEY] = payload


def render_pending_project_apply(box: Any) -> None:
    """Render the Project Mode diff preview and deterministic Apply button."""
    payload = st.session_state.get(_PENDING_PROJECT_APPLY_KEY)
    if not payload:
        result = st.session_state.get(_PROJECT_APPLY_RESULT_KEY)
        if result:
            box.success(
                "Project Mode dosyaları hedef klasöre yazıldı: "
                f"`{result.get('integration_target_path')}`"
            )
            written = result.get("integration_written_files") or []
            if written:
                box.caption(
                    "Yazılan dosyalar: "
                    + ", ".join(f"`{filename}`" for filename in written)
                )
        return

    with box.container():
        st.subheader("Project Mode Diff Preview")
        st.info("Dosyalar henüz yazılmadı. İncele, sonra uygula.")
        st.caption(f"Hedef: `{payload['target_path']}`")
        if payload.get("mcp_root"):
            st.caption(f"MCP kökü: `{payload['mcp_root']}`")

        actions = payload.get("file_actions") or []
        if actions:
            st.markdown("**Dosya aksiyonları:**")
            for item in actions:
                st.markdown(f"- `{item['file']}` — `{item['action']}`")

        diff = payload.get("diff") or ""
        if diff:
            st.markdown("**Unified diff:**")
            st.code(diff, language="diff")
        else:
            st.success("Üretilen dosyalar mevcut içerikle aynı görünüyor.")

        columns = st.columns([1, 1])
        apply_clicked = columns[0].button(
            "Değişiklikleri uygula",
            type="primary",
            key=f"apply_project_{payload['task_id']}",
        )
        discard_clicked = columns[1].button(
            "Ön izlemeyi kapat",
            key=f"discard_project_{payload['task_id']}",
        )
        if discard_clicked:
            st.session_state.pop(_PENDING_PROJECT_APPLY_KEY, None)
            st.rerun()
        if apply_clicked:
            result = asyncio.run(
                apply_project_files(payload["target_path"], payload["code"])
            )
            record_project_apply(
                project_path=payload["target_path"],
                task_id=str(payload["task_id"]),
                written_files=list(result.get("integration_written_files") or []),
            )
            _clear_project_registry_cache()
            st.session_state[_PROJECT_APPLY_RESULT_KEY] = result
            st.session_state.pop(_PENDING_PROJECT_APPLY_KEY, None)
            st.rerun()


def render_tracker(box: Any, statuses: dict[str, str], iteration: int) -> None:
    """Render the compact flow tracker into the given placeholder."""
    cells = [
        f"{_ICON[statuses.get(key, 'wait')]} {label}" for key, label in STAGES
    ]
    box.markdown(f"**İterasyon {iteration}**  ·  " + "  →  ".join(cells))


def next_stage(node: str, update: dict[str, Any]) -> str | None:
    """Return the stage that becomes active after `node` completes."""
    if update.get("should_abort"):
        return None
    linear = {
        "project_intake": "project_brief",
        "project_brief": "task_classifier",
        "task_classifier": "rag",
        "rag": "analyst",
        "analyst": "developer",
        "developer": "reviewer",
        "reviewer": "qa",
        "qa": "supervisor",
    }
    if node in linear:
        return linear[node]
    if node == "supervisor":
        status = update.get("status")
        if status == "RUNNING":
            return "developer"
        if status in ("SUCCESS", "COMPLETED_WITH_WARNINGS"):
            return "integrator"
    return None


def render_node_detail(node: str, update: dict[str, Any], iteration: int) -> None:
    """Add an expander showing the full output of a completed agent."""
    label = _LABELS.get(node, node)
    with st.expander(f"✅ {label}  ·  iterasyon {iteration}", expanded=True):
        if node == "project_intake":
            if not update.get("project_summary"):
                st.caption("Project mode kapalı; repo intake atlandı.")
                return
            if update.get("project_path"):
                st.markdown(f"Proje klasörü: `{update['project_path']}`")
            if update.get("project_mcp_root"):
                st.caption(f"MCP kökü: `{update['project_mcp_root']}`")
            if update.get("project_path_mismatch"):
                st.error(
                    "Seçilen klasör ile MCP server'ın kullandığı klasör farklı. "
                    "Yanlış repo üzerinde işlem yapmamak için akış durduruldu."
                )
            st.info(str(update["project_summary"]))
            if update.get("project_files") == []:
                st.warning(
                    "Seçilen klasörde metin/kod dosyası bulunamadı. Bu durumda "
                    "ajan mevcut dosyaları düzenlemek yerine yeni dosya önerisi "
                    "üretir."
                )
            focus_terms = update.get("project_focus_terms") or []
            if focus_terms:
                st.caption("Odak terimleri: " + ", ".join(f"`{term}`" for term in focus_terms))
            relevant_files = update.get("project_relevant_files") or []
            if relevant_files:
                st.markdown("**İlgili dosyalar:**")
                for filename in relevant_files:
                    st.markdown(f"- `{filename}`")
            excerpts = update.get("project_file_excerpts") or []
            if excerpts:
                with st.expander("Bağlama alınan dosya alıntıları", expanded=False):
                    for excerpt in excerpts[:4]:
                        filename = excerpt.get("file")
                        content = excerpt.get("content")
                        if not filename or not isinstance(content, str):
                            continue
                        st.caption(str(filename))
                        preview = content[:800]
                        if excerpt.get("truncated") or len(content) > 800:
                            preview += "\n..."
                        st.code(preview, language="text")
            matches = update.get("project_search_matches") or []
            if matches:
                st.markdown(f"**Arama eşleşmeleri:** {len(matches)}")
                for match in matches[:8]:
                    st.caption(
                        f"{match.get('file')}:{match.get('line')} — "
                        f"{match.get('text')}"
                    )
            git_status = update.get("project_git_status")
            if git_status:
                st.markdown("**Git durumu:**")
                if "not a git repository" in str(git_status):
                    st.info("Bu klasör git reposu değil; diff ve dirty-state bilgisi yok.")
                st.code(str(git_status), language="text")
            git_diff = update.get("project_git_diff")
            if git_diff:
                st.markdown("**Diff özeti:**")
                st.code(str(git_diff), language="text")
        elif node == "project_brief":
            if not update.get("project_brief"):
                st.caption("Project mode kapalı; proje brief atlandı.")
                return
            st.info(str(update["project_brief"]))
            stack = update.get("project_stack") or []
            if stack:
                st.markdown("**Stack / teknoloji sinyalleri:**")
                for item in stack:
                    st.markdown(f"- `{item}`")
            entrypoints = update.get("project_entrypoints") or []
            if entrypoints:
                st.markdown("**Muhtemel çalıştırma girişleri:**")
                for item in entrypoints:
                    st.markdown(f"- `{item}`")
            test_commands = update.get("project_test_commands") or []
            if test_commands:
                st.markdown("**Muhtemel test / doğrulama komutları:**")
                for item in test_commands:
                    st.markdown(f"- `{item}`")
            risks = update.get("project_risks") or []
            if risks:
                st.markdown("**Riskler:**")
                for item in risks:
                    st.warning(item)
            brief_files = update.get("project_brief_files") or []
            if brief_files:
                st.caption(
                    "Brief kaynakları: "
                    + ", ".join(f"`{filename}`" for filename in brief_files)
                )
        elif node == "task_classifier":
            profile = update.get("task_profile", "?")
            st.markdown(f"Seçilen profil: `{profile}`")
            if profile in {"docs", "project"}:
                st.warning(
                    "`docs` profili Markdown/text dokümantasyon çıktısı üretir. "
                    "`project` profili mevcut kaynak dosyalarını doğrudan "
                    "değiştirmek yerine `PROJECT_PROPOSAL.md` üretir; somut "
                    "HTML/static değişiklikleri static web profiline yönlendirilir."
                )
            if update.get("task_profile_reason"):
                st.caption(str(update["task_profile_reason"]))
        elif node == "rag":
            sources = update.get("rag_sources") or []
            if sources:
                st.markdown(f"Bilgi tabanından **{len(sources)} parça** çekti:")
                for source in sources:
                    st.markdown(f"- `{source}`")
            else:
                status = update.get("rag_status", "empty")
                message = update.get("rag_message") or "RAG bağlamı yok."
                if status == "disabled":
                    st.info(message)
                elif status == "unavailable":
                    st.warning(message)
                else:
                    st.info(message)
        elif node == "analyst":
            steps = update.get("plan") or []
            st.markdown(f"Görevi **{len(steps)} adıma** böldü:")
            for index, step in enumerate(steps, 1):
                st.markdown(f"{index}. {step}")
        elif node == "developer":
            approach = update.get("dev_approach")
            if approach:
                st.markdown("**Yaklaşım — Developer ne düşündü:**")
                st.info(approach)
            assumptions = update.get("dev_assumptions") or []
            if assumptions:
                st.markdown("**Varsayımlar ve kararlar:**")
                for item in assumptions:
                    st.markdown(f"- {item}")
            code = update.get("code") or {}
            st.markdown(f"**{len(code)} dosya** üretti / güncelledi:")
            for filename, content in code.items():
                st.markdown(f"`{filename}`")
                st.code(content, language=_code_language(filename))
            if _primary_html_file(code) is not None:
                render_static_web_preview(code)
        elif node == "reviewer":
            findings = update.get("review_feedback") or []
            if not findings:
                st.success("Bulgu yok — kod temiz.")
            else:
                st.markdown(f"**{len(findings)} bulgu** raporladı:")
                for finding in findings:
                    st.markdown(f"**[{finding.severity}]** {finding.issue}")
                    if finding.suggestion:
                        st.caption(f"Öneri: {finding.suggestion}")
        elif node == "qa":
            results = update.get("test_results")
            if results is not None:
                summary = f"{results.passed} test geçti, {results.failed} kaldı"
                (st.success if results.failed == 0 else st.error)(summary)
            test_cases = update.get("test_cases") or []
            if test_cases:
                if _is_static_validation(update.get("test_code")):
                    title = "**Static web validasyonları:**"
                elif _is_advisory_validation(update.get("test_code")):
                    title = "**Advisory validasyonları:**"
                else:
                    title = "**Test senaryoları:**"
                st.markdown(title)
                for index, case in enumerate(test_cases, 1):
                    st.markdown(f"{index}. {case}")
            test_code = update.get("test_code")
            if test_code:
                if _is_static_validation(test_code) or _is_advisory_validation(test_code):
                    st.markdown("**Validasyon modu:**")
                    st.code(test_code, language="text")
                else:
                    st.markdown("**Test kodu:**")
                    st.code(test_code, language="python")
            if results is not None and results.output:
                if _is_static_validation(update.get("test_code")):
                    output_title = "**Static web validasyon çıktısı:**"
                elif _is_advisory_validation(update.get("test_code")):
                    output_title = "**Advisory validasyon çıktısı:**"
                else:
                    output_title = "**pytest çıktısı:**"
                st.markdown(output_title)
                st.code(results.output, language="text")
        elif node == "supervisor":
            st.markdown(f"**Karar:** {update.get('status')}")
            history = update.get("issue_count_history")
            if history:
                st.caption(f"İterasyon başına sorun sayısı: {history}")
        elif node == "integrator":
            planned_files = update.get("integration_planned_files") or []
            written_files = update.get("integration_written_files") or []
            if update.get("integration_preview_only"):
                st.info("Project Mode ön izleme modunda; hedef klasöre yazılmadı.")
                if update.get("integration_target_path"):
                    st.markdown(f"Hedef: `{update['integration_target_path']}`")
                if planned_files:
                    st.markdown("**Yazılacak dosyalar:**")
                    for filename in planned_files:
                        st.markdown(f"- `{filename}`")
                if update.get("integration_message"):
                    st.caption(str(update["integration_message"]))
                return
            if written_files:
                st.success("Project Mode çıktısı hedef klasöre yazıldı.")
                if update.get("integration_target_path"):
                    st.markdown(f"Hedef: `{update['integration_target_path']}`")
                st.markdown("**Yazılan dosyalar:**")
                for filename in written_files:
                    st.markdown(f"- `{filename}`")
                if update.get("integration_message"):
                    st.caption(str(update["integration_message"]))
                return
            if update.get("integration_committed"):
                st.success(
                    "Üretilen kod yerel bir git feature branch'ine commit edildi."
                )
            else:
                st.warning("Integrator commit oluşturamadı veya commit atlanmış.")
            if update.get("integration_branch"):
                st.markdown(f"Branch: `{update['integration_branch']}`")
            if update.get("integration_message"):
                st.caption(str(update["integration_message"]))


def render_result(box: Any, state: dict[str, Any]) -> None:
    """Render the final result: overall status and the produced code."""
    status = state.get("status", "?")
    box.subheader("Sonuç")
    if status == "SUCCESS":
        box.success(f"Tamamlandı — {status}")
    elif status == "COMPLETED_WITH_WARNINGS":
        box.warning(f"Tamamlandı — {status}")
    else:
        box.error(f"Tamamlanamadı — {status}")

    results = state.get("test_results")
    if results is not None:
        box.write(f"**Testler:** {results.passed} geçti, {results.failed} kaldı")

    if state.get("is_degraded"):
        box.warning("Bu çalışma degraded model havuzuyla tamamlandı.")

    if state.get("node_error"):
        box.markdown("**Node hatası:**")
        box.code(str(state["node_error"]), language="text")

    if state.get("rag_status"):
        box.write(
            f"**RAG:** {state.get('rag_status')} "
            f"({state.get('rag_chunk_count', 0)} parça)"
        )
        if state.get("rag_message"):
            box.caption(str(state["rag_message"]))

    if state.get("task_profile"):
        box.write(f"**Profil:** `{state['task_profile']}`")
        if state.get("task_profile") in {"docs", "project"}:
            box.warning(
                "`docs` profili Markdown/text dokümantasyon çıktısı üretir. "
                "`project` çıktısı kaynak dosya yerine `PROJECT_PROPOSAL.md` "
                "olarak beklenir."
            )
        if state.get("task_profile_reason"):
            box.caption(str(state["task_profile_reason"]))

    if state.get("project_summary"):
        box.write(f"**Project:** {state['project_summary']}")
        if state.get("project_path"):
            box.caption(f"Proje klasörü: `{state['project_path']}`")
        if state.get("project_mcp_root"):
            box.caption(f"MCP kökü: `{state['project_mcp_root']}`")
        if state.get("project_path_mismatch"):
            box.error(
                "Seçilen klasör ile MCP server kökü farklıydı; akış güvenlik "
                "için durduruldu."
            )
        if state.get("project_files") == []:
            box.warning(
                "Seçilen klasörde metin/kod dosyası bulunamadı; çıktı yeni "
                "dosya önerisi olarak değerlendirilmeli."
            )
        relevant_files = state.get("project_relevant_files") or []
        if relevant_files:
            box.caption(
                "İlgili dosyalar: "
                + ", ".join(f"`{filename}`" for filename in relevant_files[:8])
            )

    if state.get("project_brief"):
        box.write(f"**Project Brief:** {state['project_brief']}")
        if state.get("project_test_commands"):
            box.caption(
                "Test komutları: "
                + ", ".join(
                    f"`{command}`" for command in state["project_test_commands"][:4]
                )
            )
        risks = state.get("project_risks") or []
        if risks:
            box.caption("Riskler: " + " | ".join(str(risk) for risk in risks[:3]))

    if state.get("integration_branch"):
        box.write(f"**Git branch:** `{state['integration_branch']}`")
        if state.get("integration_committed"):
            box.success(str(state.get("integration_message") or "Commit oluşturuldu."))
        else:
            box.warning(str(state.get("integration_message") or "Commit atlandı."))

    written_files = state.get("integration_written_files") or []
    planned_files = state.get("integration_planned_files") or []
    if state.get("integration_preview_only") and planned_files:
        box.info(
            "Project Mode ön izleme modunda kaldı; hedef klasöre yazılmadı."
        )
        box.caption(
            "Yazılacak dosyalar: "
            + ", ".join(f"`{name}`" for name in planned_files)
        )
        actions = state.get("integration_file_actions") or []
        if actions:
            box.markdown("**Dosya aksiyonları:**")
            for item in actions:
                box.markdown(f"- `{item['file']}` — `{item['action']}`")
        if state.get("integration_diff"):
            box.caption("Unified diff aşağıdaki Project Mode Diff Preview panelinde.")
    if written_files:
        box.success(
            "Project Mode dosyaları hedef klasöre yazıldı: "
            f"`{state.get('integration_target_path')}`"
        )
        box.caption("Yazılan dosyalar: " + ", ".join(f"`{name}`" for name in written_files))

    code = state.get("code") or {}
    for filename, content in code.items():
        box.markdown(f"**{filename}**")
        box.code(content, language=_code_language(filename))
    if _primary_html_file(code) is not None:
        with box.expander("Static web ön izleme", expanded=True):
            render_static_web_preview(code)


def render_history() -> None:
    """Render the collapsible panel of past workflow runs."""
    history = load_history()
    with st.expander(f"📋 Geçmiş Görevler ({len(history)})"):
        if not history:
            st.caption(
                "Henüz çalıştırılmış görev yok. Bir görev çalıştırınca "
                "burada listelenir."
            )
            return
        st.dataframe(
            [
                {
                    "Zaman": entry.get("timestamp", "?"),
                    "Görev": str(entry.get("task", ""))[:60],
                    "Durum": entry.get("status", "?"),
                    "Test": (
                        f"{entry.get('tests_passed', 0)}/"
                        f"{entry.get('tests_passed', 0) + entry.get('tests_failed', 0)}"
                    ),
                    "İterasyon": entry.get("iterations", 0),
                }
                for entry in history
            ],
            width="stretch",
            hide_index=True,
        )


def render_project_history(
    project: ProjectRecord | None,
    checkpoints: list[ProjectCheckpoint],
) -> None:
    """Render history scoped to the currently selected project."""
    title = (
        f"📋 Teknik Checkpoint'ler · {project['name']}"
        if project is not None
        else "📋 Teknik Checkpoint'ler"
    )
    with st.expander(f"{title} ({len(checkpoints)})", expanded=False):
        if not checkpoints:
            st.caption("Bu proje için henüz checkpoint yok.")
            return
        st.dataframe(
            [
                {
                    "Zaman": checkpoint["created_at"],
                    "Görev": checkpoint["task"][:80],
                    "Durum": checkpoint["status"],
                    "Profil": checkpoint["task_profile"],
                    "Test": (
                        f"{checkpoint['tests_passed']}/"
                        f"{checkpoint['tests_passed'] + checkpoint['tests_failed']}"
                    ),
                    "Planlanan": ", ".join(checkpoint["planned_files"][:3]),
                    "Yazılan": ", ".join(checkpoint["written_files"][:3]),
                }
                for checkpoint in checkpoints
            ],
            width="stretch",
            hide_index=True,
        )


def _project_chat_events(
    timeline: list[ProjectTimelineEvent],
) -> list[ProjectTimelineEvent]:
    """Return project conversation events in chronological display order."""
    return [
        event
        for event in reversed(timeline)
        if event["kind"] in {"user_message", "assistant_message", "project_apply"}
    ]


def _project_chat_role(event: ProjectTimelineEvent) -> str:
    """Return the Streamlit chat role for a project timeline event."""
    return "user" if event["kind"] == "user_message" else "assistant"


def _project_chat_body(event: ProjectTimelineEvent) -> str:
    """Return user-facing chat text for a project timeline event."""
    if event["kind"] != "project_apply":
        return event["body"]

    raw_files = event["metadata"].get("written_files", [])
    written_files = [str(item) for item in raw_files] if isinstance(raw_files, list) else []
    if written_files:
        return (
            "Değişiklikleri projeye yazdım: "
            + ", ".join(f"`{filename}`" for filename in written_files)
            + "."
        )
    return "Değişiklikleri uygulama adımı tamamlandı; yazılan dosya görünmüyor."


def render_project_conversation(
    project: ProjectRecord | None,
    timeline: list[ProjectTimelineEvent],
) -> None:
    """Render the selected project as a chat-first workspace."""
    project_name = project["name"] if project is not None else "Proje"
    st.subheader(f"Proje Sohbeti · {project_name}")
    events = _project_chat_events(timeline)
    if not events:
        st.caption(
            "Bu projede henüz sohbet yok. Mesaj sohbet/durum ise doğrudan "
            "yanıtlanır; analiz veya kod görevi ise ajan akışı başlar."
        )
        return

    for event in events[-12:]:
        with st.chat_message(_project_chat_role(event)):
            st.markdown(_project_chat_body(event))
            st.caption(event["created_at"])


def compose_project_assistant_response(state: dict[str, Any]) -> str:
    """Compose a user-facing Project Mode response from workflow state."""
    status = str(state.get("status") or "UNKNOWN")
    if status == "SUCCESS":
        opener = "Tamam, bu turu başarıyla tamamladım."
    elif status == "COMPLETED_WITH_WARNINGS":
        opener = "Turu tamamladım, ama dikkat edilmesi gereken uyarılar var."
    else:
        opener = "Bu tur tamamlanamadı; güvenli tarafta kalıp durdum."

    lines = [opener]
    if state.get("project_summary"):
        lines.append(f"Projeyi okuma özeti: {state['project_summary']}")
    if state.get("task_profile"):
        lines.append(f"Seçilen çalışma profili: `{state['task_profile']}`.")

    results = state.get("test_results")
    if results is not None:
        lines.append(f"Doğrulama sonucu: {results.passed} geçti, {results.failed} kaldı.")

    planned_files = list(state.get("integration_planned_files") or [])
    written_files = list(state.get("integration_written_files") or [])
    if written_files:
        lines.append(
            "Dosyaları hedef projeye yazdım: "
            + ", ".join(f"`{name}`" for name in written_files)
            + "."
        )
    elif state.get("integration_preview_only") and planned_files:
        lines.append(
            "Değişiklikleri henüz yazmadım. Diff hazır; inceleyip "
            "`Değişiklikleri uygula` ile projeye yazabilirsin."
        )
        lines.append(
            "Hazır dosyalar: " + ", ".join(f"`{name}`" for name in planned_files) + "."
        )
    elif planned_files:
        lines.append(
            "Planlanan dosyalar: "
            + ", ".join(f"`{name}`" for name in planned_files)
            + "."
        )

    risks = list(state.get("project_risks") or [])
    if risks:
        lines.append("Gördüğüm ana risk: " + str(risks[0]))
    if state.get("node_error"):
        lines.append(f"Hata detayı teknik akışta duruyor: `{state['node_error']}`")

    return "\n\n".join(lines)


def project_chat_context(
    project: ProjectRecord | None,
    checkpoints: list[ProjectCheckpoint],
    timeline: list[ProjectTimelineEvent],
    project_path: str,
) -> ProjectChatContext:
    """Build the small context object used by the Project Chat router."""
    fallback_name = Path(project_path).name if project_path else "Proje"
    return ProjectChatContext(
        project_name=project["name"] if project is not None else fallback_name,
        project_path=project_path,
        last_task=project["last_task"] if project is not None else "",
        last_status=project["last_status"] if project is not None else "",
        stack=tuple(project["project_stack"]) if project is not None else (),
        checkpoint_count=len(checkpoints),
        timeline_count=len(timeline),
    )


def refresh_project_panels(
    project_path: str,
    conversation_slot: Any | None,
    summary_slot: Any | None,
    history_slot: Any | None,
) -> None:
    """Refresh Project Mode panels after a chat or workflow write."""
    _clear_project_registry_cache()
    fresh_project_record = load_project(project_path)
    fresh_project_checkpoints = load_project_checkpoints(project_path, 5)
    fresh_project_history = load_project_checkpoints(project_path, 20)
    fresh_project_timeline = load_project_timeline(project_path, 30)
    if conversation_slot is not None:
        conversation_slot.empty()
        with conversation_slot.container():
            render_project_conversation(fresh_project_record, fresh_project_timeline)
    if summary_slot is not None:
        summary_slot.empty()
        with summary_slot.container():
            render_project_memory_summary(
                fresh_project_record,
                fresh_project_checkpoints,
                fresh_project_timeline,
            )
    if history_slot is not None:
        history_slot.empty()
        with history_slot.container():
            render_project_history(fresh_project_record, fresh_project_history)


async def run_workflow(
    task: str,
    mode: RunMode,
    project_path: str,
    project_memory: str,
    project_apply_changes: bool,
    max_iterations: int,
    use_rag: bool,
    status_box: Any,
    degraded_box: Any,
    tracker_box: Any,
    detail_container: Any,
    result_box: Any,
) -> dict[str, Any]:
    """Run the workflow, updating the UI live as each agent completes."""
    statuses = {key: "wait" for key, _ in STAGES}
    iteration = 0

    status_box.info("Model hazırlanıyor...")
    pool = build_default_pool()
    set_pool(pool)
    await pool.warm_up()
    is_degraded = pool.is_degraded
    if is_degraded:
        degraded_box.warning(
            "Model havuzu degraded modda: bazı kabiliyetler fallback'e "
            "düşebilir veya istek başarısız olabilir."
        )
    else:
        degraded_box.empty()

    workflow = build_workflow()
    initial: AgentState = {
        "task": task,
        "task_id": uuid.uuid4().hex[:8],
        "mode": mode,
        "iteration": 0,
        "status": "RUNNING",
        "max_iterations": max_iterations,
        "use_rag": use_rag,
        "is_degraded": is_degraded,
    }
    if mode == "project":
        initial["project_path"] = project_path
        initial["project_memory"] = project_memory
        initial["project_apply_changes"] = project_apply_changes
    profile, profile_reason = classify_task_profile(initial)
    initial["task_profile"] = profile
    initial["task_profile_reason"] = profile_reason

    statuses["project_intake"] = "active"
    render_tracker(tracker_box, statuses, iteration)
    status_box.info("Ajanlar çalışıyor...")

    final_state: dict[str, Any] = dict(initial)

    async for chunk in workflow.astream(
        initial, stream_mode="updates", config={"recursion_limit": 50}
    ):
        for node, raw_update in chunk.items():
            update = raw_update or {}
            final_state.update(update)
            statuses[node] = "done"
            iteration = final_state.get("iteration", 0)

            if update or node not in {"project_intake", "project_brief"}:
                with detail_container:
                    render_node_detail(node, update, iteration)

            nxt = next_stage(node, update)
            if node == "supervisor" and nxt == "developer":
                for key in _LOOP_STAGES:
                    statuses[key] = "wait"
            if nxt is not None:
                statuses[nxt] = "active"
            render_tracker(tracker_box, statuses, iteration)

    await pool.aclose()
    status_box.empty()
    _store_pending_project_apply(final_state)
    assistant_response = ""
    if mode == "project":
        assistant_response = compose_project_assistant_response(final_state)
        final_state["assistant_response"] = assistant_response
    render_result(result_box, final_state)
    record_run(final_state)
    record_project_checkpoint(final_state)
    if mode == "project" and project_path:
        task_id = str(final_state.get("task_id") or "")
        record_project_message(
            project_path=project_path,
            role="user",
            body=task,
            task_id=task_id,
        )
        record_project_message(
            project_path=project_path,
            role="assistant",
            body=assistant_response,
            task_id=task_id,
            metadata={
                "status": str(final_state.get("status") or ""),
                "task_profile": str(final_state.get("task_profile") or ""),
                "planned_files": list(
                    final_state.get("integration_planned_files") or []
                ),
                "written_files": list(
                    final_state.get("integration_written_files") or []
                ),
            },
        )
    _clear_project_registry_cache()
    return final_state


st.set_page_config(page_title="Multi-Agent Code Team", page_icon="🤖")
st.title("🤖 Multi-Agent Code Team")
st.caption("Yerel LLM'lerle çalışan çok-ajanlı kod geliştirme ekibi")

cfg_project_record: ProjectRecord | None = None
cfg_project_checkpoints: list[ProjectCheckpoint] = []
cfg_project_history: list[ProjectCheckpoint] = []
cfg_project_timeline: list[ProjectTimelineEvent] = []
cfg_project_conversation_slot: Any | None = None
cfg_project_summary_slot: Any | None = None
cfg_project_history_slot: Any | None = None

with st.sidebar:
    st.header("Ayarlar")
    cfg_mode_label = st.radio(
        "Çalışma modu",
        ["Yeni kod görevi", "Proje modu"],
        index=1,
        horizontal=True,
    )
    cfg_mode: RunMode = "project" if cfg_mode_label == "Proje modu" else "generate"
    cfg_max_iterations = st.slider("Maksimum iterasyon", min_value=1, max_value=5, value=3)
    cfg_use_rag = st.toggle("RAG (bilgi tabanı)", value=True)
    cfg_project_apply_changes = False
    cfg_project_memory = ""
    if cfg_mode == "project":
        st.success("Project Mode aktif")
        st.caption(
            "İlk adımlar repo dosyalarını, git durumunu ve Project Brief'i toplar."
        )
        render_project_registry_selector(_cached_load_projects())
        cfg_project_path = render_project_folder_picker(PROJECT_ROOT)
        cfg_project_record = ensure_project_open(cfg_project_path)
        cfg_project_checkpoints = _cached_load_project_checkpoints(
            cfg_project_path,
            5,
        )
        cfg_project_history = _cached_load_project_checkpoints(
            cfg_project_path,
            20,
        )
        cfg_project_timeline = _cached_load_project_timeline(cfg_project_path, 30)
        cfg_project_memory = project_memory_summary(
            cfg_project_record,
            cfg_project_checkpoints,
            cfg_project_timeline,
        )
        cfg_project_summary_slot = st.empty()
        with cfg_project_summary_slot.container():
            render_project_memory_summary(
                cfg_project_record,
                cfg_project_checkpoints,
                cfg_project_timeline,
            )
        render_project_management_panel(cfg_project_record, cfg_project_path)
        st.caption(
            "Başarılı sonuçta önce diff gösterilir; dosyalar yalnızca "
            "Değişiklikleri uygula butonuyla yazılır."
        )
    else:
        cfg_project_path = ""
    st.caption(
        "Maksimum iterasyon: Developer-Reviewer döngüsünün üst sınırı. "
        "RAG kapalıyken ajanlar standart bağlamı olmadan çalışır."
    )

if cfg_mode == "project":
    cfg_project_conversation_slot = st.empty()
    with cfg_project_conversation_slot.container():
        render_project_conversation(cfg_project_record, cfg_project_timeline)
    cfg_project_history_slot = st.empty()
    with cfg_project_history_slot.container():
        render_project_history(cfg_project_record, cfg_project_history)
else:
    render_history()

if cfg_mode == "project":
    st.caption(
        "Ajan akışı arka planda çalışır; teknik Project/Developer/QA adımları "
        "yalnızca detay panelinde görünür."
    )
else:
    default_task = DEFAULT_TASK

render_pending_project_apply(st.container())

if cfg_mode == "project":
    submitted_project_task = st.chat_input(DEFAULT_PROJECT_TASK)
    task_input = submitted_project_task or ""
    go = submitted_project_task is not None
else:
    task_input = st.text_area("Görev", value=default_task, height=110)
    go = st.button("▶ Çalıştır", type="primary")

if go:
    clean_task = task_input.strip()
    if not clean_task:
        st.error("Lütfen bir görev girin.")
    else:
        if cfg_mode == "project" and cfg_project_conversation_slot is not None:
            cfg_project_conversation_slot.empty()
            with cfg_project_conversation_slot.container():
                render_project_conversation(cfg_project_record, cfg_project_timeline)
                with st.chat_message("user"):
                    st.markdown(clean_task)

        should_run_workflow = True
        if cfg_mode == "project":
            chat_context = project_chat_context(
                cfg_project_record,
                cfg_project_checkpoints,
                cfg_project_timeline,
                cfg_project_path,
            )
            with st.spinner("Mesaj niyeti okunuyor..."):
                chat_decision = asyncio.run(
                    route_project_chat_intent(clean_task, chat_context)
                )
            should_run_workflow = chat_decision.should_run_workflow
            if not should_run_workflow:
                route_label = format_project_chat_route(chat_decision)
                with st.spinner("Yanıt hazırlanıyor..."):
                    assistant_response = asyncio.run(
                        answer_project_chat_direct(
                            clean_task,
                            chat_decision,
                            chat_context,
                        )
                    )
                st.caption(f"Yönlendirme: `{route_label}`.")
                task_id = uuid.uuid4().hex[:8]
                record_project_message(
                    project_path=cfg_project_path,
                    role="user",
                    body=clean_task,
                    task_id=task_id,
                    metadata={
                        "intent": chat_decision.intent,
                        "router_source": chat_decision.routed_by,
                        "router_confidence": chat_decision.confidence,
                        "routed_direct": True,
                    },
                )
                record_project_message(
                    project_path=cfg_project_path,
                    role="assistant",
                    body=assistant_response,
                    task_id=task_id,
                    metadata={
                        "intent": chat_decision.intent,
                        "router_source": chat_decision.routed_by,
                        "router_confidence": chat_decision.confidence,
                        "routed_direct": True,
                        "router_reason": chat_decision.reason,
                    },
                )
                if cfg_project_record is not None:
                    refresh_project_panels(
                        cfg_project_path,
                        cfg_project_conversation_slot,
                        cfg_project_summary_slot,
                        cfg_project_history_slot,
                    )
                elif cfg_project_conversation_slot is not None:
                    cfg_project_conversation_slot.empty()
                    with cfg_project_conversation_slot.container():
                        render_project_conversation(
                            cfg_project_record,
                            cfg_project_timeline,
                        )
                        with st.chat_message("user"):
                            st.markdown(clean_task)
                        with st.chat_message("assistant"):
                            st.markdown(assistant_response)
                st.info(
                    "Sohbet mesajı olarak yanıtlandı; teknik ajan akışı "
                    "başlatılmadı."
                )
            else:
                st.caption(
                    f"Yönlendirme: `{format_project_chat_route(chat_decision)}`; "
                    "teknik ajan akışı başlatılıyor."
                )

        if should_run_workflow:
            status_ph = st.empty()
            degraded_ph = st.empty()
            if cfg_mode == "project":
                technical_panel = st.expander("Teknik akış detayları", expanded=False)
                with technical_panel:
                    tracker_ph = st.empty()
                    detail_box = st.container()
                    st.divider()
                    result_ph = st.container()
            else:
                tracker_ph = st.empty()
                st.markdown("### Akış Detayları")
                detail_box = st.container()
                st.divider()
                result_ph = st.container()
            asyncio.run(
                run_workflow(
                    clean_task,
                    cfg_mode,
                    cfg_project_path,
                    cfg_project_memory,
                    cfg_project_apply_changes,
                    cfg_max_iterations,
                    cfg_use_rag,
                    status_ph,
                    degraded_ph,
                    tracker_ph,
                    detail_box,
                    result_ph,
                )
            )
            if cfg_mode == "project":
                refresh_project_panels(
                    cfg_project_path,
                    cfg_project_conversation_slot,
                    cfg_project_summary_slot,
                    cfg_project_history_slot,
                )
            render_pending_project_apply(st.container())
