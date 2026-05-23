"""Direct-response agent for Project Mode chat messages."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent
from app.graph.state import AgentState
from app.llm.pool import Capability


class ProjectChatResponse(BaseModel):
    """A direct chat response that does not start the workflow."""

    response: str = Field(
        description=(
            "A concise, natural response in the user's language. Do not claim "
            "that files were read or changed unless the provided context says so."
        )
    )


class ProjectChatResponderAgent(BaseAgent[ProjectChatResponse]):
    """Answers non-workflow Project Mode chat/status/help/clarify messages."""

    name = "ProjectChatResponder"
    capability = Capability.REASONER
    temperature = 0.3

    def output_schema(self) -> type[ProjectChatResponse]:
        return ProjectChatResponse

    def system_prompt(self) -> str:
        return (
            "You are the chat responder for a project-aware coding assistant. "
            "The router has already decided this message should NOT start the "
            "Developer/Reviewer/QA workflow. Answer naturally in the user's "
            "language, using the provided project context only.\n\n"
            "Rules:\n"
            "- Do not write or propose code unless the user explicitly asks a "
            "conceptual question about code.\n"
            "- Do not say you inspected files, ran tests, or changed anything "
            "unless the context explicitly says so.\n"
            "- For status, summarize the known project/checkpoint facts.\n"
            "- For clarify, ask one short clarifying question.\n"
            "- Keep the response short and conversational."
        )

    def build_user_message(self, state: AgentState) -> str:
        return (
            f"USER MESSAGE:\n{state['task']}\n\n"
            f"PROJECT / ROUTER CONTEXT:\n{state.get('project_memory') or '(none)'}"
        )
