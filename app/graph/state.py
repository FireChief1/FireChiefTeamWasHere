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
TaskProfile = Literal["python", "static_web", "node_js", "docs", "project"]


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
        mode: Whether the workflow generates code, reviews code, or works with
            project-level repository context.
        task_profile: The implementation profile selected for this task.
        task_profile_reason: Human-readable reason for the selected profile.
        max_iterations: The Developer-Reviewer loop cap for this run.
        use_rag: Whether to retrieve RAG context for this run.
        project_path: Target project folder for project-mode intake and writes.
        project_mcp_root: Effective root reported by the project MCP server.
        project_path_mismatch: True if selected path and MCP root differ.
        project_apply_changes: Whether Project Mode may write generated files.
        project_files: Text-oriented project files found during project intake.
        project_relevant_files: Files selected as most relevant to the task.
        project_search_matches: Search matches that explain relevance.
        project_file_excerpts: Small excerpts from relevant files for grounding.
        project_edit_targets: Full content of files the task names for editing.
        project_git_status: Current repository status summary.
        project_git_diff: Bounded git diff summary for the current repository.
        project_summary: Human-readable project intake summary.
        project_focus_terms: Task-derived search terms used for project intake.
        project_brief: Deterministic project profile summary.
        project_stack: Detected languages, frameworks, and project technologies.
        project_entrypoints: Likely run commands or primary files.
        project_test_commands: Detected automated verification commands.
        project_risks: Project-level risks inferred from files and git state.
        project_brief_files: Config files read to build the project brief.
        project_memory: Previous project registry/checkpoint context, including
            bounded compacted/semantic memory when available.
        project_chat_intent: Project Chat router intent that admitted workflow.
        project_chat_action: Concrete Project Chat action that admitted workflow.
        project_chat_route_source: Whether the route came from policy/model/fallback.
        project_chat_confidence: Router confidence for this workflow admission.
        project_vision_context: Optional analysis of an attached image/screenshot.
        plan: The ordered implementation steps from the Analyst.
        code: The generated source files, keyed by filename.
        dev_approach: The Developer's explanation of how it approached the task.
        dev_assumptions: Assumptions and uncertainties the Developer noted.
        dev_repair_attempted: True when Developer retried with validation feedback.
        dev_validation_error: Deterministic validation error from Developer output.
        dev_rejected_code: Invalid generated files kept for technical debugging.
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
        integration_target_path: Project folder written by Project Mode.
        integration_planned_files: Project Mode files proposed for writing.
        integration_file_actions: Create/modify/unchanged preview per file.
        integration_diff: Unified diff for Project Mode preview.
        integration_written_files: Files written into the project folder.
        integration_preview_only: True when Project Mode stopped before writing.
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
    mode: Literal["generate", "review", "project"]
    task_profile: TaskProfile
    task_profile_reason: str
    max_iterations: int
    use_rag: bool
    project_path: str
    project_mcp_root: str
    project_path_mismatch: bool
    project_apply_changes: bool
    project_files: list[str]
    project_relevant_files: list[str]
    project_search_matches: list[dict[str, object]]
    project_file_excerpts: list[dict[str, object]]
    project_edit_targets: list[dict[str, object]]
    project_git_status: str
    project_git_diff: str
    project_summary: str
    project_focus_terms: list[str]
    project_brief: str
    project_stack: list[str]
    project_entrypoints: list[str]
    project_test_commands: list[str]
    project_risks: list[str]
    project_brief_files: list[str]
    project_memory: str
    project_chat_intent: str
    project_chat_action: str
    project_chat_language: str
    project_chat_route_source: str
    project_chat_confidence: float
    project_vision_context: str
    plan: list[str]
    code: dict[str, str]
    dev_approach: str
    dev_assumptions: list[str]
    dev_repair_attempted: bool
    dev_validation_error: str
    dev_rejected_code: dict[str, str]
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
    integration_target_path: str
    integration_planned_files: list[str]
    integration_file_actions: list[dict[str, str]]
    integration_diff: str
    integration_written_files: list[str]
    integration_preview_only: bool
    iteration: int
    issue_count_history: list[int]
    best_code: dict[str, str]
    status: Status
    node_error: str | None
    should_abort: bool
    is_degraded: bool
