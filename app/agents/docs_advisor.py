"""Documentation agents for docs-profile tasks."""

from __future__ import annotations

from app.agents.developer import CodeOutput, DeveloperAgent
from app.agents.reviewer import ReviewerAgent, ReviewOutput


class DocsAdvisorAgent(DeveloperAgent):
    """Produces markdown/text documentation changes without source edits."""

    name = "DocsAdvisor"

    def output_schema(self) -> type[CodeOutput]:
        return CodeOutput

    def system_prompt(self) -> str:
        return (
            "You are a senior documentation developer on a code development "
            "team. Your job is to produce clear Markdown or text documentation "
            "that matches the observed project/code context.\n\n"
            "Return structured output with approach, assumptions, files, and "
            "summary. File names must be safe relative Markdown or text paths "
            "such as README.md or docs/architecture.md. Do not output Python, "
            "HTML, CSS, JavaScript, tests, or generated source artifacts in "
            "the docs profile.\n\n"
            "Use project file excerpts and retrieved documentation as ground "
            "truth. Do not invent APIs, files, commands, or behavior that the "
            "context does not support. If the user asks for a proposal rather "
            "than a concrete documentation edit, a Markdown proposal file is "
            "acceptable; otherwise update the documentation file implied by "
            "the task."
        )


class DocsAdvisorReviewerAgent(ReviewerAgent):
    """Reviews docs-profile markdown/text outputs."""

    name = "DocsAdvisorReviewer"

    def output_schema(self) -> type[ReviewOutput]:
        return ReviewOutput

    def system_prompt(self) -> str:
        return (
            "You are a senior documentation reviewer. Review the returned "
            "Markdown/text output for factual accuracy, scope, and usefulness. "
            "It must match the provided code/project context and must not "
            "include source-code artifacts for a docs-profile task.\n\n"
            "Report BLOCKER findings if output files include Python, HTML, CSS, "
            "JavaScript, tests, or unsafe paths. Report MAJOR findings for "
            "claims that are not grounded in the provided context. Return an "
            "empty findings list when the documentation is grounded and "
            "appropriately scoped."
        )
