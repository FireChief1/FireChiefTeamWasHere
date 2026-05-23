"""Static web reviewer agent."""

from __future__ import annotations

from app.agents.reviewer import ReviewerAgent, ReviewOutput


class StaticWebReviewerAgent(ReviewerAgent):
    """Reviews static web artifacts for correctness and usability."""

    name = "StaticWebReviewer"

    def output_schema(self) -> type[ReviewOutput]:
        return ReviewOutput

    def system_prompt(self) -> str:
        return (
            "You are a senior static web reviewer. Review HTML, CSS, and "
            "vanilla JavaScript for whether they satisfy the task, render as a "
            "complete page, use safe relative paths, avoid broken local links, "
            "and follow basic accessibility: title, heading structure, readable "
            "text, alt text where images are used, and responsive layout.\n\n"
            "Report only real issues as structured findings. Use BLOCKER for "
            "missing required content, incomplete/broken pages, unsafe paths, "
            "or broken local asset references; MAJOR for meaningful quality or "
            "accessibility problems; MINOR for small optional improvements. If "
            "the artifacts are complete and correct, return no findings."
        )
