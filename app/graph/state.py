"""The shared state that flows through the multi-agent workflow.

A single AgentState object is threaded through every node of the LangGraph
workflow. Each node reads the fields it needs and returns updates. The state
is treated as immutable per invocation, which keeps parallel pipeline tasks
isolated from one another.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import BaseModel, Field

Severity = Literal["BLOCKER", "MAJOR", "MINOR"]
Status = Literal["RUNNING", "SUCCESS", "COMPLETED_WITH_WARNINGS", "FAILED"]


class FeedbackItem(BaseModel):
    """A single finding produced by the Reviewer agent.

    Attributes:
        severity: How serious the finding is.
        issue: A description of what is wrong.
        suggestion: An optional concrete fix.
    """

    severity: Severity = Field(description="Severity: BLOCKER, MAJOR, or MINOR.")
    issue: str = Field(description="What is wrong with the code.")
    suggestion: str = Field(default="", description="How to fix the issue.")


class TestResults(BaseModel):
    """The outcome of running the QA agent's tests.

    Attributes:
        passed: Number of tests that passed.
        failed: Number of tests that failed.
        total: Total number of tests run.
        output: Captured output from the test runner.
    """

    passed: int = 0
    failed: int = 0
    total: int = 0
    output: str = Field(default="", description="Captured test runner output.")

    @property
    def all_passed(self) -> bool:
        """Return True if at least one test ran and none failed."""
        return self.total > 0 and self.failed == 0


class AgentState(TypedDict, total=False):
    """The workflow state passed between LangGraph nodes.

    Declared with ``total=False`` so a node may return a partial update. The
    fields are populated progressively: the Analyst adds ``plan``, the
    Developer adds ``code``, the Reviewer adds ``review_feedback``, and so on.

    Attributes:
        task: The original task description from the user.
        mode: Whether the workflow generates new code or reviews existing code.
        plan: The ordered implementation steps from the Analyst.
        code: The generated source files, keyed by filename.
        rag_context: Coding-standard chunks retrieved for the current step.
        review_feedback: Findings from the Reviewer.
        test_results: The outcome from the QA agent.
        iteration: The current Developer-Reviewer loop iteration.
        issue_count_history: Issue count per iteration, for oscillation detection.
        best_code: The lowest-issue code version seen so far.
        status: The overall workflow status.
        node_error: A traceback message set by the node error boundary.
        should_abort: True when the error boundary has requested termination.
        is_degraded: True when the LLM pool is running on the fallback only.
    """

    task: str
    mode: Literal["generate", "review"]
    plan: list[str]
    code: dict[str, str]
    rag_context: list[str]
    review_feedback: list[FeedbackItem]
    test_results: TestResults
    iteration: int
    issue_count_history: list[int]
    best_code: dict[str, str]
    status: Status
    node_error: str | None
    should_abort: bool
    is_degraded: bool
