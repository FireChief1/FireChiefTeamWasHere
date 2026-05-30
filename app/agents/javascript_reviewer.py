"""Node.js / JavaScript reviewer agent."""

from __future__ import annotations

from app.agents.reviewer import ReviewerAgent, ReviewOutput


class JavaScriptReviewerAgent(ReviewerAgent):
    """Reviews Node.js / JavaScript modules for correctness and quality."""

    name = "JavaScriptReviewer"

    def output_schema(self) -> type[ReviewOutput]:
        return ReviewOutput

    def system_prompt(self) -> str:
        return (
            "You are a senior Node.js/JavaScript reviewer. Review the code for "
            "whether it satisfies the task, is correct, uses modern JavaScript, "
            "exports its public API so it can be imported and tested, handles "
            "edge cases, and avoids unsafe patterns (eval, unhandled rejections, "
            "blocking the event loop).\n\n"
            "Report only real issues as structured findings. Use BLOCKER for "
            "broken or incorrect logic, syntax errors, or security problems; "
            "MAJOR for meaningful quality issues; MINOR for small optional "
            "improvements. If the code is complete and correct, return no "
            "findings."
        )
