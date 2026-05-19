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
        task_id: A short unique identifier for this task run.
        mode: Whether the workflow generates new code or reviews existing code.
        max_iterations: The Developer-Reviewer loop cap for this run.
        use_rag: Whether to retrieve RAG context for this run.
        plan: The ordered implementation steps from the Analyst.
        code: The generated source files, keyed by filename.
        dev_approach: The Developer's explanation of how it approached the task.
        dev_assumptions: Assumptions and uncertainties the Developer noted.
        rag_context: Coding-standard chunks retrieved for the current step.
        rag_sources: The document names the RAG chunks were retrieved from.
        rag_status: Whether RAG was retrieved, empty, disabled, or unavailable.
        rag_message: Human-readable RAG status detail for the UI.
        rag_chunk_count: Number of retrieved chunks.
        review_feedback: Findings from the Reviewer.
        test_results: The outcome from the QA agent.
        test_code: The pytest test file the QA agent generated and ran.
        test_cases: A plain-language description of each generated test.
        integration_message: Human-readable git integration result.
        integration_branch: Local branch used for the generated task commit.
        integration_committed: True if the Integrator created a commit.
        iteration: The current Developer-Reviewer loop iteration.
        issue_count_history: Issue count per iteration, for oscillation detection.
        best_code: The lowest-issue code version seen so far.
        status: The overall workflow status.
        node_error: A traceback message set by the node error boundary.
        should_abort: True when the error boundary has requested termination.
        is_degraded: True when the LLM pool is running on the fallback only.
    """

    task: str
    task_id: str
    mode: Literal["generate", "review"]
    max_iterations: int
    use_rag: bool
    plan: list[str]
    code: dict[str, str]
    dev_approach: str
    dev_assumptions: list[str]
    rag_context: list[str]
    rag_sources: list[str]
    rag_status: Literal["disabled", "retrieved", "empty", "unavailable"]
    rag_message: str
    rag_chunk_count: int
    review_feedback: list[FeedbackItem]
    test_results: TestResults
    test_code: str
    test_cases: list[str]
    integration_message: str
    integration_branch: str
    integration_committed: bool
    iteration: int
    issue_count_history: list[int]
    best_code: dict[str, str]
    status: Status
    node_error: str | None
    should_abort: bool
    is_degraded: bool
