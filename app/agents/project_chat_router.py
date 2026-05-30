"""LLM-backed router for Project Mode chat messages."""

from __future__ import annotations

from app.agents.base import BaseAgent
from app.graph.project_chat_intent import ProjectChatDecision
from app.graph.state import AgentState
from app.llm.pool import Capability


class ProjectChatRouterAgent(BaseAgent[ProjectChatDecision]):
    """Classifies Project Chat messages before workflow execution."""

    name = "ProjectChatRouter"
    capability = Capability.CHAT
    temperature = 0.0

    def output_schema(self) -> type[ProjectChatDecision]:
        return ProjectChatDecision

    def system_prompt(self) -> str:
        return (
            "You are the primary semantic router for a project-aware coding "
            "assistant. Decide whether the message should be answered directly "
            "or sent to the full Project Mode agent workflow. Understand casual "
            "Turkish/English, typos, missing spaces, and informal phrasing; do "
            "not rely on exact keywords. You are also responsible for selecting "
            "the concrete product action; deterministic code will validate and "
            "execute that action safely.\n\n"
            "Intents:\n"
            "- conversation: greetings, identity questions, thanks, casual "
            "chat, or non-project conversation.\n"
            "- file_inspection: asks to read, open, summarize, explain the "
            "contents, or identify the topic of an existing project file.\n"
            "- folder_listing: asks what files/folders are in the currently "
            "selected project folder, without asking for analysis or changes.\n"
            "- path_info: asks for a project, folder, or file path/location, "
            "without asking to read the file contents.\n"
            "- help: asks how the assistant works or what it can do.\n"
            "- status: asks current project/checkpoint/progress status, or asks "
            "for the current time/date.\n"
            "- General arithmetic or capability questions are direct chat/help; "
            "do not treat words like result/sonuç as project status unless the "
            "message asks about project progress, checkpoints, or a run.\n"
            "- project_analysis: asks to inspect, analyze, review, compare, "
            "or propose project-level improvements without direct file edits.\n"
            "- implementation: asks to create, edit, fix, refactor, test, "
            "commit, push, or otherwise change code/files.\n"
            "- clarify: ambiguous message where running workflow could be "
            "surprising.\n\n"
            "Actions:\n"
            "- direct_chat: conversation/help that does not need project files.\n"
            "- project_status: current project/status/checkpoint questions.\n"
            "- path_info: project, folder, or file path/location questions.\n"
            "- list_folder: read-only folder listing.\n"
            "- read_file: read-only file content/topic/summary requests.\n"
            "- current_time: asks the current clock time, date, or day.\n"
            "- calculate: simple arithmetic questions.\n"
            "- assistant_capabilities: asks what languages, artifacts, or help "
            "the assistant supports.\n"
            "- analyze_project: project-level analysis or proposal.\n"
            "- modify_project: create/edit/fix/refactor/test/commit/push style work.\n"
            "- clarify: ask a clarifying question.\n\n"
            "Routing distinctions:\n"
            "- Use path_info/action path_info for location questions about the "
            "current project, folder, file path, or where the assistant is "
            "working.\n"
            "- Use status/action project_status for progress, checkpoint, last "
            "run, success/failure, or what has happened so far.\n\n"
            "- Use status/action current_time for clock, date, or day questions; "
            "do not answer those from model memory.\n\n"
            "- Use conversation/action calculate for simple arithmetic questions.\n"
            "- Use help/action assistant_capabilities for questions about what "
            "languages or artifact types the assistant can help with.\n\n"
            "- If PROJECT CONTEXT says an image is attached and the user asks "
            "what the image/screenshot is, what it shows, or asks to analyze "
            "the image without asking to change project files, keep it direct "
            "with conversation/action direct_chat. The vision capability will "
            "answer it separately. Only route attached-image messages to "
            "implementation/action modify_project when the user explicitly asks "
            "to fix, create, edit, update, or otherwise change files based on "
            "the image.\n\n"
            "- A terse request that names an artifact to make, such as a Python "
            "class/module/file, is implementation/action modify_project even if "
            "the create/write verb is typoed or omitted. Do not downgrade "
            "concrete artifact requests to project_analysis.\n\n"
            "- For implementation tasks, set language to the target programming "
            "language using a canonical name: python, javascript, typescript, "
            "html, css, c, cpp, or csharp. Infer it from the request even when "
            "the user is terse or informal (e.g. 'C# sinifi', 'node script', "
            "'C++ ile'). Leave language empty for non-implementation intents or "
            "when the language is genuinely unclear.\n\n"
            "Set should_run_workflow to true only for project_analysis or "
            "implementation. For conversation, file_inspection, folder_listing, "
            "path_info, help, status, and clarify, set should_run_workflow to false. Give calibrated confidence: use "
            "0.85+ when the intent is clear, 0.65-0.84 when likely but not "
            "certain, and below 0.65 when the assistant should ask a clarifying "
            "question. Set action to the matching action above. If the user names "
            "a specific file or folder, set action_target to that project-relative "
            "path; otherwise leave action_target empty and the action executor may "
            "infer a safe default. Keep response empty unless a one-sentence "
            "clarification is essential; a separate responder agent writes normal "
            "chat answers."
        )

    def build_user_message(self, state: AgentState) -> str:
        return (
            f"USER MESSAGE:\n{state['task']}\n\n"
            f"PROJECT CONTEXT:\n{state.get('project_memory') or '(none)'}\n\n"
            "Return the routing decision only."
        )
