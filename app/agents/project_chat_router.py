"""LLM-backed router for Project Mode chat messages."""

from __future__ import annotations

from app.agents.base import BaseAgent
from app.graph.project_chat_intent import ProjectChatDecision
from app.graph.state import AgentState
from app.llm.pool import Capability


class ProjectChatRouterAgent(BaseAgent[ProjectChatDecision]):
    """Classifies Project Chat messages before workflow execution."""

    name = "ProjectChatRouter"
    capability = Capability.REASONER
    temperature = 0.0

    def output_schema(self) -> type[ProjectChatDecision]:
        return ProjectChatDecision

    def system_prompt(self) -> str:
        return (
            "You are the primary semantic router for a project-aware coding "
            "assistant. Decide whether the message should be answered directly "
            "or sent to the full Project Mode agent workflow. Understand casual "
            "Turkish/English, typos, missing spaces, and informal phrasing; do "
            "not rely on exact keywords.\n\n"
            "Intents:\n"
            "- conversation: greetings, identity questions, thanks, casual "
            "chat, or non-project conversation.\n"
            "- help: asks how the assistant works or what it can do.\n"
            "- status: asks current project/checkpoint/progress status.\n"
            "- project_analysis: asks to inspect, analyze, review, compare, "
            "or propose project-level improvements without direct file edits.\n"
            "- implementation: asks to create, edit, fix, refactor, test, "
            "commit, push, or otherwise change code/files.\n"
            "- clarify: ambiguous message where running workflow could be "
            "surprising.\n\n"
            "Set should_run_workflow to true only for project_analysis or "
            "implementation. For conversation, help, status, and clarify, set "
            "should_run_workflow to false. Give calibrated confidence: use "
            "0.85+ when the intent is clear, 0.65-0.84 when likely but not "
            "certain, and below 0.65 when the assistant should ask a clarifying "
            "question. Keep response empty unless a one-sentence clarification "
            "is essential; a separate responder agent writes normal chat "
            "answers."
        )

    def build_user_message(self, state: AgentState) -> str:
        return (
            f"USER MESSAGE:\n{state['task']}\n\n"
            f"PROJECT CONTEXT:\n{state.get('project_memory') or '(none)'}\n\n"
            "Return the routing decision only."
        )
