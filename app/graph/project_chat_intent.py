"""Intent routing for the Project Mode chat surface.

Project Mode is chat-first, but not every chat message is a code task. This
module keeps conversational/status/help messages out of the expensive agent
workflow while still letting clear project-analysis and implementation tasks
enter the LangGraph path.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.graph.project_actions import (
    action_from_chat_decision,
    detect_read_only_project_action,
    execute_read_only_project_action,
    normalize_project_message,
)
from app.graph.state import AgentState
from app.llm.pool import build_default_pool

ProjectChatIntent = Literal[
    "conversation",
    "file_inspection",
    "folder_listing",
    "help",
    "path_info",
    "status",
    "project_analysis",
    "implementation",
    "clarify",
]
ProjectChatRouteSource = Literal["policy", "model", "fallback"]

_WORKFLOW_INTENTS = {"project_analysis", "implementation"}
_DIRECT_INTENTS = {
    "conversation",
    "file_inspection",
    "folder_listing",
    "help",
    "path_info",
    "status",
    "clarify",
}
_MODEL_CONFIDENCE_FLOOR = 0.65


@dataclass(frozen=True)
class ProjectChatContext:
    """Small, UI-safe context block used by the chat intent router."""

    project_name: str = "Proje"
    project_path: str = ""
    last_task: str = ""
    last_status: str = ""
    stack: tuple[str, ...] = ()
    checkpoint_count: int = 0
    timeline_count: int = 0

    def router_summary(self) -> str:
        """Return a compact context summary for the model router."""
        lines = [
            f"Project name: {self.project_name or 'Proje'}",
            f"Project path: {self.project_path or '(not selected)'}",
            f"Last status: {self.last_status or '(none)'}",
            f"Last task: {self.last_task or '(none)'}",
            "Stack: " + (", ".join(self.stack) if self.stack else "(unknown)"),
            f"Checkpoint count: {self.checkpoint_count}",
            f"Timeline event count: {self.timeline_count}",
        ]
        return "\n".join(lines)


class ProjectChatDecision(BaseModel):
    """Structured Project Chat routing decision."""

    intent: ProjectChatIntent = Field(
        description=(
            "conversation, help, status, project_analysis, implementation, "
            "file_inspection, folder_listing, path_info, or clarify"
        )
    )
    should_run_workflow: bool = Field(
        description="True only when the LangGraph agent workflow should run."
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Router confidence from 0.0 to 1.0.",
    )
    reason: str = Field(default="", description="Short routing rationale.")
    response: str = Field(
        default="",
        description="Optional direct response when the workflow should not run.",
    )
    routed_by: ProjectChatRouteSource = Field(
        default="model",
        description="Whether the final route came from policy, model, or fallback.",
    )


ModelRouter = Callable[
    [str, ProjectChatContext], Awaitable[ProjectChatDecision]
]
DirectResponder = Callable[
    [str, ProjectChatDecision, ProjectChatContext], Awaitable[str]
]


def deterministic_project_chat_decision(
    message: str,
    context: ProjectChatContext | None = None,
) -> ProjectChatDecision | None:
    """Return policy-only routing decisions before the model router.

    The LLM router owns semantic classification. This deterministic layer is
    intentionally narrow: empty messages and high-confidence read-only file
    actions are handled without starting the expensive workflow.
    """
    chat_context = context or ProjectChatContext()
    text = _clean(message)
    if not text:
        return _direct(
            "clarify",
            "Empty Project Chat message.",
            confidence=1.0,
            routed_by="policy",
        )

    action = detect_read_only_project_action(message, chat_context.project_path)
    if action is not None and action.action == "read_file":
        return _direct(
            "file_inspection",
            action.reason,
            confidence=action.confidence,
            routed_by=action.routed_by,
        )
    if action is not None and action.action == "path_info":
        return _direct(
            "path_info",
            action.reason,
            confidence=action.confidence,
            routed_by=action.routed_by,
        )
    if action is not None and action.action == "list_folder":
        return _direct(
            "folder_listing",
            action.reason,
            confidence=action.confidence,
            routed_by=action.routed_by,
        )

    return None


async def route_project_chat_intent(
    message: str,
    context: ProjectChatContext | None = None,
    *,
    model_router: ModelRouter | None = None,
) -> ProjectChatDecision:
    """Route a Project Chat message through guardrails, model, and fallback."""
    chat_context = context or ProjectChatContext()
    deterministic = deterministic_project_chat_decision(message, chat_context)
    if deterministic is not None:
        return deterministic

    router = model_router or _model_project_chat_router
    try:
        decision = await router(message, chat_context)
    except Exception as exc:  # noqa: BLE001 - router fallback is intentional
        return _direct(
            "clarify",
            f"Model router failed safely: {exc}",
            confidence=0.0,
            routed_by="fallback",
        )
    return normalize_project_chat_decision(decision)


def normalize_project_chat_decision(
    decision: ProjectChatDecision,
) -> ProjectChatDecision:
    """Normalize a model decision into the product's routing contract."""
    if decision.confidence < _MODEL_CONFIDENCE_FLOOR:
        return _direct(
            "clarify",
            (
                "Model router confidence was below "
                f"{_MODEL_CONFIDENCE_FLOOR:.2f}."
            ),
            confidence=decision.confidence,
            response=decision.response,
            routed_by="fallback",
        )

    intent = decision.intent
    if intent in _WORKFLOW_INTENTS:
        return ProjectChatDecision(
            intent=intent,
            should_run_workflow=True,
            confidence=decision.confidence,
            reason=decision.reason,
            response="",
            routed_by="model",
        )
    if intent in _DIRECT_INTENTS:
        return ProjectChatDecision(
            intent=intent,
            should_run_workflow=False,
            confidence=decision.confidence,
            reason=decision.reason,
            response=decision.response,
            routed_by="model",
        )
    return _direct(
        "clarify",
        f"Unsupported router intent: {intent}",
        confidence=decision.confidence,
        routed_by="fallback",
    )


async def answer_project_chat_direct(
    message: str,
    decision: ProjectChatDecision,
    context: ProjectChatContext,
    *,
    responder: DirectResponder | None = None,
) -> str:
    """Generate a direct Project Chat response for non-workflow routes."""
    action = action_from_chat_decision(
        message=message,
        intent=decision.intent,
        should_run_workflow=decision.should_run_workflow,
        confidence=decision.confidence,
        reason=decision.reason,
        routed_by=decision.routed_by,
        project_path=context.project_path,
    )
    action_response = execute_read_only_project_action(
        action,
        message,
        context.project_path,
    )
    if action_response is not None:
        return action_response

    if decision.response.strip():
        return decision.response.strip()

    model_responder = responder or _model_project_chat_responder
    try:
        response = await model_responder(message, decision, context)
    except Exception:  # noqa: BLE001 - direct chat has a deterministic fallback
        return compose_project_chat_direct_response(decision, context)

    clean_response = response.strip()
    if clean_response:
        return clean_response
    return compose_project_chat_direct_response(decision, context)


def compose_project_chat_direct_response(
    decision: ProjectChatDecision,
    context: ProjectChatContext,
) -> str:
    """Compose the deterministic fallback for a direct Project Chat route."""
    if decision.response.strip() and decision.intent != "status":
        return decision.response.strip()

    if decision.intent == "conversation":
        return (
            "Ben bu seçili proje üzerinde çalışan yerel proje asistanıyım. "
            "Sohbet, durum ve yardım mesajlarını burada yanıtlarım; net analiz "
            "veya kod/değişiklik görevi verdiğinde ajan akışını başlatırım."
        )

    if decision.intent == "file_inspection":
        return "Hangi dosyayı okumamı istediğini belirtir misin?"

    if decision.intent == "path_info":
        action = action_from_chat_decision(
            message="",
            intent=decision.intent,
            should_run_workflow=False,
            confidence=decision.confidence,
            reason=decision.reason,
            routed_by=decision.routed_by,
            project_path=context.project_path,
        )
        response = execute_read_only_project_action(action, "", context.project_path)
        return response or "Hangi dosyanın yolunu istediğini belirtir misin?"

    if decision.intent == "folder_listing":
        action = action_from_chat_decision(
            message="",
            intent=decision.intent,
            should_run_workflow=False,
            confidence=decision.confidence,
            reason=decision.reason,
            routed_by=decision.routed_by,
            project_path=context.project_path,
        )
        response = execute_read_only_project_action(action, "", context.project_path)
        return response or "Klasör içeriğini okuyamadım."

    if decision.intent == "help":
        return (
            "Bu projede sohbet edebilir, durum sorabilir, proje analizi "
            "isteyebilir veya açık bir kod/değişiklik görevi verebilirsin. "
            "Kod ya da dosya işi netleşmeden Developer/QA akışına girmem."
        )

    if decision.intent == "status":
        status = context.last_status or "henüz çalışma yok"
        task = context.last_task or "henüz görev yok"
        stack = ", ".join(context.stack) if context.stack else "belirsiz"
        return (
            f"Proje: {context.project_name or 'Proje'}\n\n"
            f"Klasör: `{context.project_path or 'seçilmedi'}`\n\n"
            f"Son durum: `{status}`\n\n"
            f"Son görev: {task}\n\n"
            f"Stack: {stack}\n\n"
            f"Checkpoint sayısı: {context.checkpoint_count}"
        )

    return (
        "Bunu güvenli tarafta sohbet olarak tuttum ve teknik ajan akışını "
        "başlatmadım. Projeyi analiz etmemi istiyorsan bunu açıkça söyle; "
        "dosya değiştirmemi istiyorsan hedefi ve beklenen değişikliği belirt."
    )


def format_project_chat_route(decision: ProjectChatDecision) -> str:
    """Format router metadata for compact UI display."""
    return (
        f"{decision.routed_by}: {decision.intent}, "
        f"confidence: {decision.confidence:.2f}"
    )


async def _model_project_chat_router(
    message: str,
    context: ProjectChatContext,
) -> ProjectChatDecision:
    """Ask the local model to classify Project Chat messages."""
    from app.agents.project_chat_router import ProjectChatRouterAgent

    pool = build_default_pool()
    try:
        await pool.warm_up()
        state: AgentState = {
            "task": message,
            "mode": "project",
            "project_path": context.project_path,
            "project_memory": context.router_summary(),
        }
        return await ProjectChatRouterAgent(pool).run(state)
    finally:
        await pool.aclose()


async def _model_project_chat_responder(
    message: str,
    decision: ProjectChatDecision,
    context: ProjectChatContext,
) -> str:
    """Ask the local model to answer a direct Project Chat message."""
    from app.agents.project_chat_responder import ProjectChatResponderAgent

    pool = build_default_pool()
    try:
        await pool.warm_up()
        state: AgentState = {
            "task": message,
            "mode": "project",
            "project_path": context.project_path,
            "project_memory": (
                context.router_summary()
                + "\n"
                + f"Router intent: {decision.intent}\n"
                + f"Router reason: {decision.reason}\n"
                + f"Router confidence: {decision.confidence:.2f}"
            ),
        }
        output = await ProjectChatResponderAgent(pool).run(state)
        return output.response
    finally:
        await pool.aclose()


def _clean(message: str) -> str:
    return normalize_project_message(message)


def _direct(
    intent: Literal[
        "conversation",
        "file_inspection",
        "folder_listing",
        "help",
        "path_info",
        "status",
        "clarify",
    ],
    reason: str,
    *,
    confidence: float = 1.0,
    response: str = "",
    routed_by: ProjectChatRouteSource = "policy",
) -> ProjectChatDecision:
    return ProjectChatDecision(
        intent=intent,
        should_run_workflow=False,
        confidence=confidence,
        reason=reason,
        response=response,
        routed_by=routed_by,
    )
