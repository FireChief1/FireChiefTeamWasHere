"""Project Chat service used by the React UI API.

The first React migration keeps the Python backend dependency-light: no web
framework is required for the service layer, and the HTTP adapter lives in
``app.api.server``.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from app.graph.project_actions import (
    ProjectActionDecision,
    action_from_chat_decision,
)
from app.graph.project_chat_intent import (
    DirectResponder,
    ModelRouter,
    ProjectChatContext,
    ProjectChatDecision,
    answer_project_chat_direct,
    format_project_chat_route,
    route_project_chat_intent,
)
from app.graph.state import AgentState
from app.graph.task_profile import classify_task_profile
from app.graph.workflow import build_workflow
from app.history import record_run
from app.llm.pool import build_default_pool, set_pool
from app.project_registry import (
    ProjectCheckpoint,
    ProjectRecord,
    ProjectTimelineEvent,
    load_project,
    load_project_checkpoints,
    load_project_timeline,
    load_projects,
    open_project,
    project_memory_summary,
    record_project_checkpoint,
    record_project_message,
)


class ProjectServiceError(Exception):
    """Raised when a project API action cannot be completed safely."""


async def handle_project_chat(
    *,
    project_path: str,
    message: str,
    max_iterations: int = 3,
    use_rag: bool = True,
    model_router: ModelRouter | None = None,
    direct_responder: DirectResponder | None = None,
) -> dict[str, Any]:
    """Route a project message and optionally run the technical workflow."""
    clean_message = message.strip()
    if not clean_message:
        raise ProjectServiceError("Message is required.")

    project = ensure_project(project_path)
    checkpoints = load_project_checkpoints(project["path"], 5)
    timeline = load_project_timeline(project["path"], 30)
    context = build_project_chat_context(
        project,
        checkpoints,
        timeline,
        project["path"],
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
    )

    if not decision.should_run_workflow:
        response = await answer_project_chat_direct(
            clean_message,
            decision,
            context,
            responder=direct_responder,
        )
        task_id = uuid.uuid4().hex[:8]
        _record_project_exchange(
            project_path=project["path"],
            task_id=task_id,
            message=clean_message,
            response=response,
            decision=decision,
            action=action,
        )
        return {
            "ranWorkflow": False,
            "assistantResponse": response,
            "route": route_payload(decision, action),
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
        metadata={
            "status": str(final_state.get("status") or ""),
            "task_profile": str(final_state.get("task_profile") or ""),
            "planned_files": list(final_state.get("integration_planned_files") or []),
            "written_files": list(final_state.get("integration_written_files") or []),
        },
    )

    refreshed = load_project(project["path"]) or project
    return {
        "ranWorkflow": True,
        "assistantResponse": response,
        "route": route_payload(decision, action),
        "project": project_payload(refreshed),
        "timeline": timeline_payloads(load_project_timeline(project["path"], 30)),
        "checkpoints": checkpoint_payloads(
            load_project_checkpoints(project["path"], 20)
        ),
        "run": run_payload(final_state),
    }


async def run_project_workflow(
    *,
    task: str,
    project: ProjectRecord,
    max_iterations: int,
    use_rag: bool,
) -> dict[str, Any]:
    """Run the LangGraph project workflow without Streamlit UI callbacks."""
    checkpoints = load_project_checkpoints(project["path"], 5)
    timeline = load_project_timeline(project["path"], 30)
    project_memory = project_memory_summary(project, checkpoints, timeline)

    pool = build_default_pool()
    try:
        set_pool(pool)
        await pool.warm_up()
        initial: AgentState = {
            "task": task,
            "task_id": uuid.uuid4().hex[:8],
            "mode": "project",
            "iteration": 0,
            "status": "RUNNING",
            "max_iterations": max_iterations,
            "use_rag": use_rag,
            "is_degraded": pool.is_degraded,
            "project_path": project["path"],
            "project_memory": project_memory,
            "project_apply_changes": False,
        }
        profile, profile_reason = classify_task_profile(initial)
        initial["task_profile"] = profile
        initial["task_profile_reason"] = profile_reason
        workflow = build_workflow()
        result = await workflow.ainvoke(initial, config={"recursion_limit": 50})
        return dict(result)
    finally:
        await pool.aclose()


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
        ),
    }


def list_projects_payload() -> list[dict[str, Any]]:
    """Return registered projects for the React sidebar."""
    return [project_payload(project) for project in load_projects()]


def build_project_chat_context(
    project: ProjectRecord | None,
    checkpoints: list[ProjectCheckpoint],
    timeline: list[ProjectTimelineEvent],
    project_path: str,
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
    )


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


def run_payload(state: dict[str, Any]) -> dict[str, Any]:
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
        "nodeError": state.get("node_error"),
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
    record_project_message(
        project_path=project_path,
        role="assistant",
        body=response,
        task_id=task_id,
        metadata=assistant_metadata,
    )
