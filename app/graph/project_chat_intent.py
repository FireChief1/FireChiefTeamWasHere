"""Intent routing for the Project Mode chat surface.

Project Mode is chat-first, but not every chat message is a code task. This
module keeps conversational/status/help messages out of the expensive agent
workflow while still letting clear project-analysis and implementation tasks
enter the LangGraph path.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.graph.project_actions import (
    ProjectActionName,
    action_from_chat_decision,
    can_calculate_message,
    execute_read_only_project_action,
    normalize_project_message,
)
from app.graph.state import AgentState
from app.llm.pool import get_pool

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
ProjectChatResponseSource = Literal["action", "router", "model", "vision", "fallback"]

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
    semantic_memory: str = ""
    has_image_attachment: bool = False

    def router_summary(self) -> str:
        """Return a compact context summary for the model router."""
        lines = [
            f"Project name: {self.project_name or 'Proje'}",
            f"Project path: {self.project_path or '(not selected)'}",
            f"Last status: {self.last_status or '(none)'}",
            f"Last task: {self.last_task or '(none)'}",
            "Stack: " + (", ".join(self.stack) if self.stack else "(unknown)"),
            f"Attached image: {'yes' if self.has_image_attachment else 'no'}",
            f"Checkpoint count: {self.checkpoint_count}",
            f"Timeline event count: {self.timeline_count}",
        ]
        return "\n".join(lines)

    def responder_summary(self, intent: ProjectChatIntent) -> str:
        """Return direct-chat context without letting history become the task."""
        lines = [
            f"Project name: {self.project_name or 'Proje'}",
            f"Project path: {self.project_path or '(not selected)'}",
            "Stack: " + (", ".join(self.stack) if self.stack else "(unknown)"),
            f"Checkpoint count: {self.checkpoint_count}",
            f"Timeline event count: {self.timeline_count}",
        ]
        if intent == "status":
            lines.extend(
                [
                    f"Last status: {self.last_status or '(none)'}",
                    f"Last task: {self.last_task or '(none)'}",
                ]
            )
        elif self.last_status:
            lines.append(
                "Previous run status is history only, not the current request: "
                f"{self.last_status}"
            )
        if self.semantic_memory:
            lines.extend(["", self.semantic_memory])
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
    action: ProjectActionName | None = Field(
        default=None,
        description="Concrete product action selected by the model router.",
    )
    action_target: str = Field(
        default="",
        description="Optional project-relative path target for the selected action.",
    )
    language: str = Field(
        default="",
        description=(
            "Target programming language for implementation tasks, e.g. python, "
            "javascript, typescript, html, css, c, cpp, csharp. Empty when not "
            "an implementation task or the language is unclear."
        ),
    )
    routed_by: ProjectChatRouteSource = Field(
        default="model",
        description="Whether the final route came from policy, model, or fallback.",
    )


@dataclass(frozen=True)
class ProjectChatDirectAnswer:
    """Direct Project Chat answer plus its source for UI transparency."""

    response: str
    response_source: ProjectChatResponseSource


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
    """Return policy-only routing decisions before the model router."""
    del context
    text = _clean(message)
    if not text:
        return _direct(
            "clarify",
            "Empty Project Chat message.",
            confidence=1.0,
            routed_by="policy",
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
    return normalize_project_chat_decision(decision, message=message)


def normalize_project_chat_decision(
    decision: ProjectChatDecision,
    *,
    message: str = "",
) -> ProjectChatDecision:
    """Normalize a model decision into the product's routing contract."""
    if can_calculate_message(message):
        return ProjectChatDecision(
            intent="conversation",
            should_run_workflow=False,
            confidence=max(decision.confidence, 0.9),
            reason="Arithmetic question handled by deterministic calculate action.",
            response="",
            action="calculate",
            action_target="",
            routed_by=decision.routed_by
            if decision.action == "calculate"
            else "fallback",
        )

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
            action=decision.action,
            action_target=decision.action_target,
            language=decision.language,
            routed_by="model",
        )
    if intent in _DIRECT_INTENTS:
        return ProjectChatDecision(
            intent=intent,
            should_run_workflow=False,
            confidence=decision.confidence,
            reason=decision.reason,
            response=decision.response,
            action=decision.action,
            action_target=decision.action_target,
            language=decision.language,
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
    answer = await answer_project_chat_direct_result(
        message,
        decision,
        context,
        responder=responder,
    )
    return answer.response


async def answer_project_chat_direct_result(
    message: str,
    decision: ProjectChatDecision,
    context: ProjectChatContext,
    *,
    responder: DirectResponder | None = None,
) -> ProjectChatDirectAnswer:
    """Generate a direct Project Chat response with response-source metadata."""
    action = action_from_chat_decision(
        message=message,
        intent=decision.intent,
        should_run_workflow=decision.should_run_workflow,
        confidence=decision.confidence,
        reason=decision.reason,
        routed_by=decision.routed_by,
        project_path=context.project_path,
        action_name=decision.action,
        action_target=decision.action_target,
    )
    action_response = execute_read_only_project_action(
        action,
        message,
        context.project_path,
    )
    if action_response is not None:
        return ProjectChatDirectAnswer(action_response, "action")

    if decision.response.strip():
        return ProjectChatDirectAnswer(decision.response.strip(), "router")

    model_responder = responder or _model_project_chat_responder
    try:
        response = await model_responder(message, decision, context)
    except Exception:  # noqa: BLE001 - direct chat has a deterministic fallback
        return ProjectChatDirectAnswer(
            compose_project_chat_direct_response(decision, context),
            "fallback",
        )

    clean_response = response.strip()
    if clean_response:
        if not is_direct_model_response_grounded(clean_response):
            return ProjectChatDirectAnswer(
                compose_project_chat_grounding_fallback(decision, context),
                "fallback",
            )
        return ProjectChatDirectAnswer(clean_response, "model")
    return ProjectChatDirectAnswer(
        compose_project_chat_direct_response(decision, context),
        "fallback",
    )


def is_direct_model_response_grounded(response: str) -> bool:
    """Return False if a direct model answer claims unexecuted work."""
    text = _clean(response)
    if not text:
        return True

    operational_claims = (
        r"\bolusturdum\b",
        r"\bolusturuldu\b",
        r"\bekledim\b",
        r"\byazdim\b",
        r"\bdegistirdim\b",
        r"\bguncelledim\b",
        r"\bduzelttim\b",
        r"\bsildim\b",
        r"\bkaydettim\b",
        r"\bokudum\b",
        r"\blisteledim\b",
        r"\bcalistirdim\b",
        r"\btest ettim\b",
        r"\bcommitledim\b",
        r"\bpushladim\b",
        r"\bcreated\b",
        r"\badded\b",
        r"\bwrote\b",
        r"\bmodified\b",
        r"\bupdated\b",
        r"\bfixed\b",
        r"\bdeleted\b",
        r"\bread\b",
        r"\blisted\b",
        r"\bran tests\b",
        r"\bcommitted\b",
        r"\bpushed\b",
    )
    return not any(re.search(pattern, text) for pattern in operational_claims)


def compose_project_chat_grounding_fallback(
    decision: ProjectChatDecision,
    context: ProjectChatContext,
) -> str:
    """Compose a safe answer when the direct model overclaims actions."""
    if decision.intent == "status":
        return compose_project_chat_direct_response(decision, context)
    return (
        "Bunu sohbet olarak tuttum; bu turda dosya oluşturmadım, okumadım, "
        "değiştirmedim veya test çalıştırmadım. Net bir analiz ya da değişiklik "
        "görevi verirsen teknik ajan akışını başlatırım."
    )


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

    pool = get_pool()
    state: AgentState = {
        "task": message,
        "mode": "project",
        "project_path": context.project_path,
        "project_memory": context.router_summary(),
    }
    return await ProjectChatRouterAgent(pool).run(state)


async def _model_project_chat_responder(
    message: str,
    decision: ProjectChatDecision,
    context: ProjectChatContext,
) -> str:
    """Ask the local model to answer a direct Project Chat message."""
    from app.agents.project_chat_responder import ProjectChatResponderAgent

    pool = get_pool()
    state: AgentState = {
        "task": message,
        "mode": "project",
        "project_path": context.project_path,
        "project_memory": (
            context.responder_summary(decision.intent)
            + "\n"
            + f"Router intent: {decision.intent}\n"
            + f"Router reason: {decision.reason}\n"
            + f"Router confidence: {decision.confidence:.2f}"
        ),
    }
    output = await ProjectChatResponderAgent(pool).run(state)
    return output.response


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
