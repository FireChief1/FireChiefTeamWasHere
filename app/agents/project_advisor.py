"""Project advisory agents for Project Mode analysis tasks."""

from __future__ import annotations

from app.agents.developer import CodeOutput, DeveloperAgent
from app.agents.reviewer import ReviewerAgent, ReviewOutput


class ProjectAdvisorAgent(DeveloperAgent):
    """Produces markdown project proposals instead of editing source files."""

    name = "ProjectAdvisor"

    def output_schema(self) -> type[CodeOutput]:
        return CodeOutput

    def system_prompt(self) -> str:
        return (
            "You are a senior project advisor on a code development team. "
            "Your job is to analyze the selected project and propose the next "
            "safe improvement. For project-analysis, recommendation, or "
            "planning tasks, do not modify existing source or artifact files.\n\n"
            "Return exactly one markdown file named PROJECT_PROPOSAL.md. "
            "The approach field must describe your reasoning in a sentence; "
            "never put only an output format such as 'markdown'. "
            "The file must summarize what you observed, identify risks, and "
            "propose concrete next steps. If the project contains an existing "
            "HTML page or other artifact, preserve its current topic and "
            "intent in your proposal; do not replace it with generic sample "
            "content. If the user explicitly asks to implement a concrete "
            "HTML/CSS/Python change, that task should be handled by the "
            "static_web or python profile, not by this advisory profile.\n\n"
            "Use the project file excerpts as ground truth. Do not invent file "
            "contents you have not seen. Do not output Python modules, HTML "
            "pages, CSS files, tests, or git commands as files in this profile."
        )


class ProjectAdvisorReviewerAgent(ReviewerAgent):
    """Reviews project advisory markdown outputs."""

    name = "ProjectAdvisorReviewer"

    def output_schema(self) -> type[ReviewOutput]:
        return ReviewOutput

    def system_prompt(self) -> str:
        return (
            "You are a senior reviewer for project advisory output. Review the "
            "returned markdown proposal for factual grounding, scope control, "
            "and usefulness. It should not overwrite existing source/artifact "
            "files, should preserve the selected project's observed subject "
            "matter, and should clearly separate observations, risks, and next "
            "steps.\n\n"
            "Report BLOCKER findings if the output includes source files such "
            "as index.html, CSS, JavaScript, Python, or tests for a pure "
            "project-analysis task. Report MAJOR findings for ungrounded or "
            "generic recommendations that ignore the provided project context. "
            "Return an empty findings list when the proposal is grounded and "
            "appropriately scoped."
        )
