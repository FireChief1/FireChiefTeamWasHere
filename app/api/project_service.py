"""Project Chat service used by the React UI API.

The first React migration keeps the Python backend dependency-light: no web
framework is required for the service layer, and the HTTP adapter lives in
``app.api.server``.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, TypedDict

from langgraph.errors import GraphRecursionError
from loguru import logger

from app.graph.project_actions import (
    ProjectActionDecision,
    action_from_chat_decision,
    normalize_project_message,
)
from app.graph.project_chat_intent import (
    DirectResponder,
    ModelRouter,
    ProjectChatContext,
    ProjectChatDecision,
    answer_project_chat_direct_result,
    format_project_chat_route,
    route_project_chat_intent,
)
from app.graph.project_output import apply_project_files
from app.graph.state import AgentState
from app.graph.task_profile import classify_task_profile
from app.graph.workflow import build_workflow
from app.history import record_run
from app.llm.pool import get_pool
from app.project_memory import (
    compact_project_exchange,
    semantic_project_memory_for_prompt,
)
from app.project_registry import (
    ProjectCheckpoint,
    ProjectRecord,
    ProjectTimelineEvent,
    load_project,
    load_project_checkpoints,
    load_project_memory_chunks,
    load_project_timeline,
    load_projects,
    open_project,
    project_memory_summary,
    record_project_apply,
    record_project_checkpoint,
    record_project_message,
)
from app.vision import (
    ImageAttachment,
    analyze_image_attachment,
    normalize_image_attachment,
)


class ProjectServiceError(Exception):
    """Raised when a project API action cannot be completed safely."""


class PendingProjectApply(TypedDict):
    """Server-side pending Project Mode apply payload."""

    token: str
    task_id: str
    target_path: str
    mcp_root: str
    code: dict[str, str]
    planned_files: list[str]
    file_actions: list[dict[str, str]]
    diff: str
    created_at: float


_PENDING_PROJECT_APPLIES: dict[str, PendingProjectApply] = {}
# A pending preview is short-lived: it is superseded by the next run for the
# same project and should not linger in the long-running server process.
_PENDING_APPLY_TTL_SECONDS = 3600.0
_MAX_PENDING_APPLIES = 32

# The Developer<->Reviewer loop is user-controllable via maxIterations. It is
# clamped to a safe range and the graph recursion limit is derived from it, so a
# large value can never exceed the limit and crash with GraphRecursionError.
_MIN_MAX_ITERATIONS = 1
_MAX_MAX_ITERATIONS = 10


def _clamp_max_iterations(value: int) -> int:
    """Clamp a user-supplied iteration count into the supported range."""
    return max(_MIN_MAX_ITERATIONS, min(int(value), _MAX_MAX_ITERATIONS))


def _recursion_limit_for(max_iterations: int) -> int:
    """Derive a graph recursion limit that comfortably fits the fix loop.

    Lead nodes (intake, brief, classifier, rag, analyst) plus one Integrator,
    plus four nodes (developer, reviewer, qa, supervisor) per iteration, with a
    safety margin.
    """
    return 12 + max_iterations * 5


async def handle_project_chat(
    *,
    project_path: str,
    message: str,
    max_iterations: int = 3,
    use_rag: bool = True,
    image_attachment: object | None = None,
    model_router: ModelRouter | None = None,
    direct_responder: DirectResponder | None = None,
) -> dict[str, Any]:
    """Route a project message and optionally run the technical workflow."""
    try:
        image = normalize_image_attachment(image_attachment)
    except ValueError as exc:
        raise ProjectServiceError(str(exc)) from exc

    clean_message = message.strip() or ("Bu görseli yorumla." if image else "")
    if not clean_message:
        raise ProjectServiceError("Message is required.")

    project = ensure_project(project_path)
    # Throttled proactive health probe for the real (non-injected) model path.
    # The threaded API server has no persistent loop for run_health_loop, so
    # this is where a down/recovered node is detected between requests.
    if model_router is None:
        await get_pool().ensure_recent_health()
    checkpoints = load_project_checkpoints(project["path"], 5)
    timeline = load_project_timeline(project["path"], 30)
    semantic_memory = semantic_project_memory_for_prompt(
        project_path=project["path"],
        query=clean_message,
    )
    context = build_project_chat_context(
        project,
        checkpoints,
        timeline,
        project["path"],
        semantic_memory=semantic_memory,
        has_image_attachment=image is not None,
    )
    decision = await route_project_chat_intent(
        clean_message,
        context,
        model_router=model_router,
    )
    action = action_from_chat_decision(
        message=clean_message,
        intent=decision.intent,
        should_run_workflow=decision.should_run_workflow,
        confidence=decision.confidence,
        reason=decision.reason,
        routed_by=decision.routed_by,
        project_path=project["path"],
        action_name=decision.action,
        action_target=decision.action_target,
    )
    vision_analysis = ""
    if image is not None:
        vision_analysis = await _analyze_project_chat_image_or_fallback(
            message=clean_message,
            image=image,
            context=context,
        )
        if not vision_analysis:
            return _project_chat_image_unavailable_response(
                project=project,
                message=clean_message,
                decision=decision,
                action=action,
                image=image,
            )

    if image is not None and _should_answer_image_directly(
        clean_message,
        decision,
        action,
    ):
        response = vision_analysis
        task_id = uuid.uuid4().hex[:8]
        _record_project_exchange(
            project_path=project["path"],
            task_id=task_id,
            message=clean_message,
            response=response,
            decision=decision,
            action=action,
            response_source="vision",
            metadata=_vision_metadata(image),
        )
        compact_project_exchange(
            project_path=project["path"],
            task_id=task_id,
            user_message=clean_message,
            assistant_response=response,
            metadata=_project_memory_metadata(
                decision,
                action,
                response_source="vision",
                extra=_vision_metadata(image),
            ),
        )
        return {
            "ranWorkflow": False,
            "assistantResponse": response,
            "route": route_payload(decision, action, response_source="vision"),
            "project": project_payload(load_project(project["path"]) or project),
            "timeline": timeline_payloads(load_project_timeline(project["path"], 30)),
            "checkpoints": checkpoint_payloads(
                load_project_checkpoints(project["path"], 20)
            ),
        }

    if not decision.should_run_workflow:
        if image is not None:
            response = vision_analysis
            task_id = uuid.uuid4().hex[:8]
            _record_project_exchange(
                project_path=project["path"],
                task_id=task_id,
                message=clean_message,
                response=response,
                decision=decision,
                action=action,
                response_source="vision",
                metadata=_vision_metadata(image),
            )
            compact_project_exchange(
                project_path=project["path"],
                task_id=task_id,
                user_message=clean_message,
                assistant_response=response,
                metadata=_project_memory_metadata(
                    decision,
                    action,
                    response_source="vision",
                    extra=_vision_metadata(image),
                ),
            )
            return {
                "ranWorkflow": False,
                "assistantResponse": response,
                "route": route_payload(decision, action, response_source="vision"),
                "project": project_payload(load_project(project["path"]) or project),
                "timeline": timeline_payloads(
                    load_project_timeline(project["path"], 30)
                ),
                "checkpoints": checkpoint_payloads(
                    load_project_checkpoints(project["path"], 20)
                ),
            }

        direct_answer = await answer_project_chat_direct_result(
            clean_message,
            decision,
            context,
            responder=direct_responder,
        )
        response = direct_answer.response
        task_id = uuid.uuid4().hex[:8]
        _record_project_exchange(
            project_path=project["path"],
            task_id=task_id,
            message=clean_message,
            response=response,
            decision=decision,
            action=action,
            response_source=direct_answer.response_source,
        )
        compact_project_exchange(
            project_path=project["path"],
            task_id=task_id,
            user_message=clean_message,
            assistant_response=response,
            metadata=_project_memory_metadata(
                decision,
                action,
                response_source=direct_answer.response_source,
            ),
        )
        return {
            "ranWorkflow": False,
            "assistantResponse": response,
            "route": route_payload(
                decision,
                action,
                response_source=direct_answer.response_source,
            ),
            "project": project_payload(load_project(project["path"]) or project),
            "timeline": timeline_payloads(load_project_timeline(project["path"], 30)),
            "checkpoints": checkpoint_payloads(
                load_project_checkpoints(project["path"], 20)
            ),
        }

    final_state = await run_project_workflow(
        task=clean_message,
        project=project,
        max_iterations=max_iterations,
        use_rag=use_rag,
        chat_decision=decision,
        chat_action=action,
        vision_context=vision_analysis,
    )
    response = compose_project_assistant_response(final_state)
    final_state["assistant_response"] = response

    record_run(final_state)
    record_project_checkpoint(final_state)
    _record_project_exchange(
        project_path=project["path"],
        task_id=str(final_state.get("task_id") or ""),
        message=clean_message,
        response=response,
        decision=decision,
        action=action,
        response_source="workflow",
        metadata={
            "status": str(final_state.get("status") or ""),
            "task_profile": str(final_state.get("task_profile") or ""),
            "planned_files": list(final_state.get("integration_planned_files") or []),
            "written_files": list(final_state.get("integration_written_files") or []),
        },
    )
    compact_project_exchange(
        project_path=project["path"],
        task_id=str(final_state.get("task_id") or ""),
        user_message=clean_message,
        assistant_response=response,
        metadata=_project_memory_metadata(
            decision,
            action,
            response_source="workflow",
            extra={
                "status": str(final_state.get("status") or ""),
                "task_profile": str(final_state.get("task_profile") or ""),
                "planned_files": list(
                    final_state.get("integration_planned_files") or []
                ),
                "written_files": list(
                    final_state.get("integration_written_files") or []
                ),
            },
        ),
    )

    refreshed = load_project(project["path"]) or project
    pending_apply = register_pending_project_apply(final_state)
    return {
        "ranWorkflow": True,
        "assistantResponse": response,
        "route": route_payload(decision, action, response_source="workflow"),
        "project": project_payload(refreshed),
        "timeline": timeline_payloads(load_project_timeline(project["path"], 30)),
        "checkpoints": checkpoint_payloads(
            load_project_checkpoints(project["path"], 20)
        ),
        "run": run_payload(final_state, pending_apply=pending_apply),
    }


async def handle_project_apply(
    *,
    project_path: str,
    apply_token: str,
) -> dict[str, Any]:
    """Apply a pending Project Mode preview from the React UI."""
    if not apply_token:
        raise ProjectServiceError("Apply token is required.")

    project = ensure_project(project_path)
    pending = _PENDING_PROJECT_APPLIES.get(apply_token)
    if pending is None:
        raise ProjectServiceError("No pending Project Mode apply was found.")

    project_root = Path(project["path"]).expanduser().resolve()
    target_root = Path(pending["target_path"]).expanduser().resolve()
    if target_root != project_root:
        raise ProjectServiceError("Pending apply does not belong to this project.")

    result = await apply_project_files(pending["target_path"], pending["code"])
    written_files = list(result.get("integration_written_files") or [])
    record_project_apply(
        project_path=pending["target_path"],
        task_id=pending["task_id"],
        written_files=written_files,
    )
    _PENDING_PROJECT_APPLIES.pop(apply_token, None)

    refreshed = load_project(project["path"]) or project
    return {
        "project": project_payload(refreshed),
        "timeline": timeline_payloads(load_project_timeline(project["path"], 30)),
        "checkpoints": checkpoint_payloads(
            load_project_checkpoints(project["path"], 20)
        ),
        "apply": {
            "targetPath": str(result.get("integration_target_path") or target_root),
            "mcpRoot": str(result.get("project_mcp_root") or pending["mcp_root"]),
            "writtenFiles": written_files,
        },
    }


async def run_project_workflow(
    *,
    task: str,
    project: ProjectRecord,
    max_iterations: int,
    use_rag: bool,
    chat_decision: ProjectChatDecision | None = None,
    chat_action: ProjectActionDecision | None = None,
    vision_context: str = "",
) -> dict[str, Any]:
    """Run the LangGraph project workflow without Streamlit UI callbacks."""
    checkpoints = load_project_checkpoints(project["path"], 5)
    semantic_memory = semantic_project_memory_for_prompt(
        project_path=project["path"],
        query=task,
    )
    # Durable project facts + recent run history only. Relevant prior exchanges
    # come solely from the query-scoped semantic memory, so the workflow prompt
    # is not flooded with unconditional top-importance chunks or a raw recent
    # chat transcript (which also duplicated the semantic section).
    project_memory = project_memory_summary(project, checkpoints)
    if semantic_memory:
        project_memory = "\n\n".join(
            part for part in (project_memory, semantic_memory) if part
        )

    pool = get_pool()
    await pool.warm_up()
    safe_max_iterations = _clamp_max_iterations(max_iterations)
    initial: AgentState = {
        "task": task,
        "task_id": uuid.uuid4().hex[:8],
        "mode": "project",
        "iteration": 0,
        "status": "RUNNING",
        "max_iterations": safe_max_iterations,
        "use_rag": use_rag,
        "is_degraded": pool.is_degraded,
        "project_path": project["path"],
        "project_memory": project_memory,
        "project_apply_changes": False,
    }
    if chat_decision is not None:
        initial["project_chat_intent"] = chat_decision.intent
        initial["project_chat_route_source"] = chat_decision.routed_by
        initial["project_chat_confidence"] = chat_decision.confidence
    if chat_action is not None:
        initial["project_chat_action"] = chat_action.action
    if vision_context:
        initial["project_vision_context"] = vision_context
    profile, profile_reason = classify_task_profile(initial)
    initial["task_profile"] = profile
    initial["task_profile_reason"] = profile_reason
    workflow = build_workflow()
    try:
        result = await workflow.ainvoke(
            initial,
            config={"recursion_limit": _recursion_limit_for(safe_max_iterations)},
        )
    except GraphRecursionError as exc:
        # Should be unreachable given the derived limit, but degrade cleanly
        # instead of surfacing a 500 if the loop ever fails to converge.
        logger.warning(f"workflow hit the recursion limit: {exc}")
        return {
            **initial,
            "status": "FAILED",
            "node_error": f"workflow stopped: recursion limit reached ({exc})",
            "should_abort": True,
        }
    return dict(result)


def ensure_project(project_path: str) -> ProjectRecord:
    """Validate and open a project registry entry."""
    resolved = Path(project_path).expanduser().resolve()
    if not resolved.exists():
        raise ProjectServiceError(f"Project path does not exist: {resolved}")
    if not resolved.is_dir():
        raise ProjectServiceError(f"Project path is not a folder: {resolved}")

    project = open_project(resolved)
    if project is None:
        raise ProjectServiceError("Project registry could not be opened.")
    return project


def list_project_bundle(path: str) -> dict[str, Any]:
    """Return one project with its recent timeline/checkpoints."""
    project = ensure_project(path)
    return {
        "project": project_payload(project),
        "timeline": timeline_payloads(load_project_timeline(project["path"], 30)),
        "checkpoints": checkpoint_payloads(load_project_checkpoints(project["path"], 20)),
        "memory": project_memory_summary(
            project,
            load_project_checkpoints(project["path"], 5),
            load_project_timeline(project["path"], 30),
            load_project_memory_chunks(project["path"], 8),
        ),
    }


def list_projects_payload() -> list[dict[str, Any]]:
    """Return registered projects for the React sidebar."""
    projects: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for project in load_projects(100):
        project_path = str(project["path"])
        if project_path in seen_paths:
            continue
        seen_paths.add(project_path)
        if _is_transient_test_project_path(project_path):
            continue
        if not Path(project_path).expanduser().exists():
            continue
        projects.append(project_payload(project))
        if len(projects) >= 30:
            break
    return projects


def _is_transient_test_project_path(project_path: str) -> bool:
    """Return True for pytest temp projects that should not clutter the UI."""
    parts = Path(project_path).expanduser().parts
    return any(
        part.startswith("pytest-") or part.startswith("pytest-of-")
        for part in parts
    )


def build_project_chat_context(
    project: ProjectRecord | None,
    checkpoints: list[ProjectCheckpoint],
    timeline: list[ProjectTimelineEvent],
    project_path: str,
    semantic_memory: str = "",
    has_image_attachment: bool = False,
) -> ProjectChatContext:
    """Build router context without importing the Streamlit UI module."""
    fallback_name = Path(project_path).name if project_path else "Proje"
    return ProjectChatContext(
        project_name=project["name"] if project is not None else fallback_name,
        project_path=project_path,
        last_task=project["last_task"] if project is not None else "",
        last_status=project["last_status"] if project is not None else "",
        stack=tuple(project["project_stack"]) if project is not None else (),
        checkpoint_count=len(checkpoints),
        timeline_count=len(timeline),
        semantic_memory=semantic_memory,
        has_image_attachment=has_image_attachment,
    )


def _should_answer_image_directly(
    message: str,
    decision: ProjectChatDecision,
    action: ProjectActionDecision,
) -> bool:
    """Keep image-description requests out of the code workflow.

    The model router remains the main decision maker, but attached images are a
    separate capability. If the user only asks what the image shows, a workflow
    would be surprising and slow. We only continue to Project Mode when the
    message clearly asks for project/file work based on the image.
    """
    if not decision.should_run_workflow:
        return True
    if action.action != "modify_project":
        return not _message_requests_project_work_from_image(message)
    return not _message_requests_project_work_from_image(message)


def _message_requests_project_work_from_image(message: str) -> bool:
    """Return True for explicit image-driven file/code work requests."""
    text = normalize_project_message(message)
    mutation_terms = (
        "duzelt",
        "coz",
        "degistir",
        "duzenle",
        "guncelle",
        "ekle",
        "sil",
        "olustur",
        "yarat",
        "hazirla",
        "yaz",
        "uygula",
        "fix",
        "solve",
        "change",
        "edit",
        "update",
        "add",
        "delete",
        "create",
        "write",
        "implement",
        "apply",
        "commit",
        "push",
        "test",
        "refactor",
    )
    artifact_terms = (
        "python",
        "py",
        "html",
        "css",
        "javascript",
        "js",
        "typescript",
        "tsx",
        "class",
        "sinif",
        "dosya",
        "file",
        "module",
        "modul",
        "fonksiyon",
        "function",
        "component",
        "api",
        "kod",
        "code",
    )
    return any(term in text for term in mutation_terms) or any(
        term in text for term in artifact_terms
    )


async def _analyze_project_chat_image_or_fallback(
    *,
    message: str,
    image: ImageAttachment,
    context: ProjectChatContext,
) -> str:
    """Return vision analysis or an empty string when vision is unavailable."""
    try:
        return await analyze_image_attachment(
            message=message,
            image=image,
            project_context=context.router_summary(),
        )
    except Exception:  # noqa: BLE001 - optional capability must fail closed
        return ""


def _project_chat_image_unavailable_response(
    *,
    project: ProjectRecord,
    message: str,
    decision: ProjectChatDecision,
    action: ProjectActionDecision,
    image: ImageAttachment,
) -> dict[str, Any]:
    """Return a safe no-workflow response when vision cannot run."""
    task_id = uuid.uuid4().hex[:8]
    response = (
        "Görseli yorumlayamadım; vision modeli hazır değil ya da çağrı başarısız "
        "oldu. Bu yüzden görsele dayanarak dosya değiştirmeye başlamadım."
    )
    metadata = {
        **_vision_metadata(image),
        "vision_error": "unavailable",
    }
    _record_project_exchange(
        project_path=project["path"],
        task_id=task_id,
        message=message,
        response=response,
        decision=decision,
        action=action,
        response_source="fallback",
        metadata=metadata,
    )
    compact_project_exchange(
        project_path=project["path"],
        task_id=task_id,
        user_message=message,
        assistant_response=response,
        metadata=_project_memory_metadata(
            decision,
            action,
            response_source="fallback",
            extra=metadata,
        ),
    )
    return {
        "ranWorkflow": False,
        "assistantResponse": response,
        "route": route_payload(decision, action, response_source="fallback"),
        "project": project_payload(load_project(project["path"]) or project),
        "timeline": timeline_payloads(load_project_timeline(project["path"], 30)),
        "checkpoints": checkpoint_payloads(load_project_checkpoints(project["path"], 20)),
    }


def compose_project_assistant_response(state: dict[str, Any]) -> str:
    """Compose the same chat-facing summary used by the Streamlit surface."""
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
        passed = int(getattr(results, "passed", 0) or 0)
        failed = int(getattr(results, "failed", 0) or 0)
        lines.append(f"Doğrulama sonucu: {passed} geçti, {failed} kaldı.")

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


def route_payload(
    decision: ProjectChatDecision,
    action: ProjectActionDecision | None = None,
    *,
    response_source: str | None = None,
) -> dict[str, Any]:
    """Serialize Project Chat router metadata."""
    payload = {
        "intent": decision.intent,
        "shouldRunWorkflow": decision.should_run_workflow,
        "confidence": decision.confidence,
        "reason": decision.reason,
        "routedBy": decision.routed_by,
        "label": format_project_chat_route(decision),
    }
    if response_source is not None:
        payload["responseSource"] = response_source
    if action is not None:
        payload.update(
            {
                "action": action.action,
                "actionTarget": action.target,
                "readOnly": action.read_only,
                "requiresWorkflow": action.requires_workflow,
                "safetyStatus": action.safety_status,
                "safetyMessage": action.safety_message,
            }
        )
    return payload


def project_payload(project: ProjectRecord) -> dict[str, Any]:
    """Serialize a project registry record."""
    return {
        "id": project["id"],
        "name": project["name"],
        "path": project["path"],
        "updatedAt": project["updated_at"],
        "lastOpenedAt": project["last_opened_at"],
        "brief": project["project_brief"],
        "stack": project["project_stack"],
        "entrypoints": project["project_entrypoints"],
        "testCommands": project["project_test_commands"],
        "risks": project["project_risks"],
        "gitStatus": project["git_status"],
        "lastTask": project["last_task"],
        "lastStatus": project["last_status"],
    }


def checkpoint_payloads(
    checkpoints: list[ProjectCheckpoint],
) -> list[dict[str, Any]]:
    """Serialize checkpoint rows."""
    return [
        {
            "id": item["id"],
            "createdAt": item["created_at"],
            "taskId": item["task_id"],
            "task": item["task"],
            "status": item["status"],
            "taskProfile": item["task_profile"],
            "summary": item["project_summary"],
            "plannedFiles": item["planned_files"],
            "writtenFiles": item["written_files"],
            "previewOnly": item["integration_preview_only"],
            "diff": item["integration_diff"],
            "testsPassed": item["tests_passed"],
            "testsFailed": item["tests_failed"],
        }
        for item in checkpoints
    ]


def timeline_payloads(events: list[ProjectTimelineEvent]) -> list[dict[str, Any]]:
    """Serialize project timeline rows oldest-first for chat rendering."""
    return [
        {
            "id": item["id"],
            "createdAt": item["created_at"],
            "kind": item["kind"],
            "title": item["title"],
            "body": item["body"],
            "metadata": item["metadata"],
            "role": item["metadata"].get("role", ""),
        }
        for item in reversed(events)
    ]


def register_pending_project_apply(state: dict[str, Any]) -> dict[str, Any] | None:
    """Store a pending preview apply payload and return its public token data."""
    if state.get("mode") != "project":
        return None
    if state.get("status") not in {"SUCCESS", "COMPLETED_WITH_WARNINGS"}:
        return None
    if state.get("project_path_mismatch"):
        return None
    if not state.get("integration_preview_only"):
        return None

    code = state.get("code") or {}
    if not isinstance(code, dict) or not code:
        return None

    target_path = str(state.get("integration_target_path") or state.get("project_path") or "")
    if not target_path:
        return None

    resolved_target = str(Path(target_path).expanduser().resolve())
    now = time.monotonic()
    _prune_pending_applies(now, supersede_target=resolved_target)

    task_id = str(state.get("task_id") or uuid.uuid4().hex[:8])
    token = uuid.uuid4().hex
    pending: PendingProjectApply = {
        "token": token,
        "task_id": task_id,
        "target_path": target_path,
        "mcp_root": str(state.get("project_mcp_root") or ""),
        "code": {str(name): str(content) for name, content in code.items()},
        "planned_files": list(state.get("integration_planned_files") or list(code)),
        "file_actions": list(state.get("integration_file_actions") or []),
        "diff": str(state.get("integration_diff") or ""),
        "created_at": now,
    }
    _PENDING_PROJECT_APPLIES[token] = pending
    return public_pending_apply_payload(pending)


def _prune_pending_applies(now: float, *, supersede_target: str = "") -> None:
    """Drop expired, superseded, and overflow pending applies.

    A new preview for a project supersedes any earlier pending apply for the
    same resolved target, so a stale token can never write outdated code. A TTL
    and a hard cap bound the dict in the long-running server process.
    """
    drop: set[str] = set()
    for token, pending in _PENDING_PROJECT_APPLIES.items():
        expired = now - pending.get("created_at", now) > _PENDING_APPLY_TTL_SECONDS
        superseded = bool(supersede_target) and _same_target(
            pending["target_path"], supersede_target
        )
        if expired or superseded:
            drop.add(token)
    for token in drop:
        _PENDING_PROJECT_APPLIES.pop(token, None)

    overflow = len(_PENDING_PROJECT_APPLIES) - _MAX_PENDING_APPLIES + 1
    if overflow > 0:
        oldest = sorted(
            _PENDING_PROJECT_APPLIES.items(),
            key=lambda item: item[1].get("created_at", 0.0),
        )
        for token, _ in oldest[:overflow]:
            _PENDING_PROJECT_APPLIES.pop(token, None)


def _same_target(left: str, right: str) -> bool:
    """Return True if two project paths resolve to the same location."""
    try:
        return str(Path(left).expanduser().resolve()) == right
    except OSError:
        return left == right


def public_pending_apply_payload(pending: PendingProjectApply) -> dict[str, Any]:
    """Return client-safe pending apply metadata without generated file content."""
    return {
        "token": pending["token"],
        "taskId": pending["task_id"],
        "targetPath": pending["target_path"],
        "mcpRoot": pending["mcp_root"],
        "plannedFiles": pending["planned_files"],
        "fileActions": pending["file_actions"],
        "diff": pending["diff"],
    }


def run_payload(
    state: dict[str, Any],
    *,
    pending_apply: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a compact technical run summary for the React detail panel."""
    results = state.get("test_results")
    return {
        "taskId": str(state.get("task_id") or ""),
        "status": str(state.get("status") or ""),
        "taskProfile": str(state.get("task_profile") or ""),
        "ragStatus": str(state.get("rag_status") or ""),
        "ragSources": list(state.get("rag_sources") or []),
        "projectSummary": str(state.get("project_summary") or ""),
        "plannedFiles": list(state.get("integration_planned_files") or []),
        "writtenFiles": list(state.get("integration_written_files") or []),
        "previewOnly": bool(state.get("integration_preview_only")),
        "diff": str(state.get("integration_diff") or ""),
        "pendingApply": pending_apply,
        "nodeError": state.get("node_error"),
        "devRepairAttempted": bool(state.get("dev_repair_attempted")),
        "devValidationError": state.get("dev_validation_error"),
        "rejectedCode": dict(state.get("dev_rejected_code") or {}),
        "tests": {
            "passed": int(getattr(results, "passed", 0) or 0),
            "failed": int(getattr(results, "failed", 0) or 0),
            "total": int(getattr(results, "total", 0) or 0),
            "output": str(getattr(results, "output", "") or ""),
        },
    }


def _record_project_exchange(
    *,
    project_path: str,
    task_id: str,
    message: str,
    response: str,
    decision: ProjectChatDecision,
    action: ProjectActionDecision | None = None,
    response_source: str = "",
    metadata: dict[str, object] | None = None,
) -> None:
    base_metadata: dict[str, object] = {
        "intent": decision.intent,
        "router_source": decision.routed_by,
        "router_confidence": decision.confidence,
        "router_reason": decision.reason,
        "routed_direct": not decision.should_run_workflow,
    }
    if action is not None:
        base_metadata.update(
            {
                "action": action.action,
                "action_target": action.target,
                "action_read_only": action.read_only,
                "action_requires_workflow": action.requires_workflow,
                "action_safety_status": action.safety_status,
                "action_safety_message": action.safety_message,
            }
        )
    record_project_message(
        project_path=project_path,
        role="user",
        body=message,
        task_id=task_id,
        metadata=base_metadata,
    )
    assistant_metadata = dict(base_metadata)
    assistant_metadata.update(metadata or {})
    if response_source:
        assistant_metadata["response_source"] = response_source
    record_project_message(
        project_path=project_path,
        role="assistant",
        body=response,
        task_id=task_id,
        metadata=assistant_metadata,
    )


def _project_memory_metadata(
    decision: ProjectChatDecision,
    action: ProjectActionDecision | None,
    *,
    response_source: str,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return normalized metadata for compacted project memory."""
    metadata: dict[str, object] = {
        "intent": decision.intent,
        "router_source": decision.routed_by,
        "router_confidence": decision.confidence,
        "router_reason": decision.reason,
        "response_source": response_source,
        "routed_direct": not decision.should_run_workflow,
    }
    if action is not None:
        metadata.update(
            {
                "action": action.action,
                "action_target": action.target,
                "action_read_only": action.read_only,
                "action_requires_workflow": action.requires_workflow,
                "action_safety_status": action.safety_status,
                "action_safety_message": action.safety_message,
            }
        )
    metadata.update(extra or {})
    return metadata


def _vision_metadata(image: ImageAttachment) -> dict[str, object]:
    """Return UI-safe metadata about an attached image."""
    return {
        "image_name": image.name,
        "image_mime_type": image.mime_type,
        "image_byte_size": image.byte_size,
    }
