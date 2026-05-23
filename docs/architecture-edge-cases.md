# Architecture Edge Cases Register

This document is a complete failure-mode register for the multi-agent code development system. It was produced by a tabletop FMEA (Failure Mode and Effects Analysis) before implementation, so that the architecture could be hardened against every identified failure mode in advance.

Each edge case lists the scenario, its impact, the resolution built into the architecture, and where the resolution is implemented.

## Severity Classification

- **CRITICAL** — would break a live demo or corrupt output. Must be handled.
- **IMPORTANT** — degrades quality or reliability but does not crash the system.
- **MINOR** — rare or low-impact; handled with logging and best-effort recovery.

## Resolution Status Legend

- **HANDLED** — the base architecture already covers this.
- **HARDENED** — a specific mechanism was added to the architecture to cover this.
- **PARTIAL** — the current implementation handles the core failure mode, but not every originally proposed enhancement.
- **PLANNED** — documented as a future extension; not implemented in the current repository.

---

## Infrastructure and Network Layer

### EC-01: A worker PC is down at startup

**Scenario:** PC1 or PC2 is powered off or unreachable when the system starts.

**Impact:** IMPORTANT — one capability (CODER or REASONER) has no primary node.

**Resolution (PARTIAL):** The `LLMPool` supports health checks and fallback routing. In the current Streamlit workflow, warm-up marks unreachable nodes unhealthy before the task starts; a long-running background health loop exists but is not started by the UI.

**Implemented in:** `llm/pool.py` — `warm_up`, `health_check_once`, `run_health_loop`, `pick_node`.

### EC-02: A worker PC crashes mid-task

**Scenario:** A PC becomes unreachable while an agent is calling it.

**Impact:** IMPORTANT — an in-flight request fails.

**Resolution (HANDLED):** Calls retry with exponential backoff implemented in the pool. After the configured number of consecutive failures, the node's circuit opens and routing skips it. The request is retried against another usable node or fallback if one is configured.

**Implemented in:** `llm/pool.py` — `_execute`, circuit breaker state per node.

### EC-03: Both worker PCs are down (DEGRADED MODE)

**Scenario:** Neither PC1 nor PC2 is reachable. Only the Mac fallback is available.

**Impact:** CRITICAL — the whole CODER/REASONER topology is gone.

**Resolution (PARTIAL):** The pool enters degraded mode when a specialized capability has no usable node. If a fallback node is configured and healthy, requests can route there; if the only node is down, the workflow fails honestly. The UI surfaces degraded mode in the run state and final result.

**Implemented in:** `llm/pool.py` — `pick_node` returns fallback for any capability when no specialized node is healthy; `is_degraded()` flag; UI banner in `ui/streamlit_app.py`.

### EC-04: Ollama cold start (model not in VRAM)

**Scenario:** The first request to a model triggers a 10-30 second load from disk into VRAM.

**Impact:** IMPORTANT — the first agent call may exceed a tight timeout.

**Resolution (HARDENED):** A **warm-up phase** runs before the workflow starts. It sends a trivial prompt ("ok") to each node so the models are resident in VRAM before real work begins. `OLLAMA_KEEP_ALIVE=30m` keeps them loaded between tasks. HTTP timeout is set generously (180s) to tolerate any remaining cold start.

**Implemented in:** `llm/pool.py` — `warm_up()` called at application startup.

### EC-05: Ollama out-of-memory on a 6GB GPU

**Scenario:** A model plus context exceeds the RTX 3050's 6GB VRAM.

**Impact:** CRITICAL — the request fails or the GPU thrashes.

**Resolution (HANDLED):** `OLLAMA_NUM_PARALLEL=1` ensures each node processes one inference at a time, so concurrent requests queue instead of competing for VRAM. Models are chosen to fit: 7B at Q4 (~4.7-5GB) leaves headroom.

**Implemented in:** Ollama systemd configuration on each PC.

---

## Agent Layer

### EC-07: Analyst produces an empty or malformed plan

**Scenario:** The Analyst returns no plan, an empty list, or unstructured garbage.

**Impact:** CRITICAL — the Developer has no instructions to act on.

**Resolution (HARDENED):** The Analyst uses structured output, so malformed responses fail at the LLM call boundary and are caught by the node error boundary. Empty or whitespace-only plan steps are removed; if the plan is still empty, the Analyst is retried once. If the retry is also empty, the workflow uses a fallback plan: "Implement directly from the task description."

**Implemented in:** `agents/analyst.py`, `agents/base.py`, `graph/nodes.py`, `graph/error_boundary.py`.

### EC-08: Developer output cannot be parsed

**Scenario:** The Developer returns prose, partial code, or a broken structured response instead of valid code.

**Impact:** CRITICAL — there is no code to review or test.

**Resolution (HARDENED):** LangChain `with_structured_output()` constrains the response to a Pydantic schema. The Developer node then applies profile-aware validation: Python tasks require safe Python modules that parse, static-web tasks require safe HTML/CSS/JS artifacts, documentation tasks require Markdown/text output, and project advisory tasks are constrained to `PROJECT_PROPOSAL.md`. Invalid output is retried once; if the retry is still invalid, non-project tasks end as FAILED with `node_error` and project advisory tasks fall back to a deterministic proposal.

**Implemented in:** `agents/developer.py`, `graph/developer_step.py`, `graph/code_validation.py` — structured output, profile-aware file validation, one retry, honest failure/fallback.

### EC-09: Developer writes code unrelated to the task

**Scenario:** The generated code compiles but does not solve the stated problem.

**Impact:** IMPORTANT — wrong solution.

**Resolution (HANDLED):** The Reviewer checks functional correctness against the original task and reports a BLOCKER. The Supervisor routes back to the Developer with that feedback. This is the normal review loop.

**Implemented in:** `agents/reviewer.py`, `agents/supervisor.py`.

### EC-10: Reviewer feedback is malformed JSON

**Scenario:** The Reviewer (a 7B model) emits broken JSON, so the Supervisor cannot parse the feedback.

**Impact:** CRITICAL — the Supervisor cannot make a routing decision.

**Resolution (HARDENED):** `with_structured_output()` constrains the Reviewer to a Pydantic feedback schema. If structured output fails after pool retries, the node error boundary fails the workflow rather than approving code with an unreadable review.

**Implemented in:** `agents/reviewer.py`, `agents/base.py`, `llm/pool.py`, `graph/error_boundary.py`.

### EC-11: Generated code contains an infinite loop and hangs pytest

**Scenario:** The Developer produces code with an infinite loop; the QA agent runs `pytest`, which never returns.

**Impact:** CRITICAL — the entire system freezes.

**Resolution (HARDENED):** Every test execution runs under a hard subprocess timeout (`subprocess.run(..., timeout=30)`). On timeout, the process is killed and the QA agent reports a failing test: `"test execution timed out — possible infinite loop"`. This becomes feedback and triggers a loop iteration.

**Implemented in:** `agents/qa.py` — subprocess timeout; MCP shell server also enforces a per-command timeout.

### EC-12: Generated code has a syntax error

**Scenario:** The code does not even parse.

**Impact:** IMPORTANT — tests cannot run.

**Resolution (HARDENED):** Profile-specific Developer output is validated before review and QA. Python syntax errors trigger one Developer retry and then a FAILED workflow if the retry is still invalid. Static-web and advisory profiles use their own artifact checks so HTML/docs/project outputs are not incorrectly forced through Python parsing. If pytest reports a collection error for Python tasks, QA parses that as a failing result and feeds it into review feedback.

**Implemented in:** `graph/developer_step.py`, `graph/code_validation.py`, `graph/qa_step.py`, `graph/static_web_qa.py`, `graph/advisory_qa.py`.

### EC-13: A node raises an unhandled Python exception

**Scenario:** A bug in node code (not an LLM error) raises an exception inside a LangGraph node.

**Impact:** CRITICAL — the exception could crash the whole workflow.

**Resolution (HARDENED):** Every node function is wrapped in an **error boundary** decorator. If a node raises, the boundary catches it, logs the full traceback, writes the error into `state.node_error`, and sets `state.should_abort = True`. All conditional edges check `should_abort` first and route directly to a FAILED end state. The system never crashes silently; it ends with an honest error report.

**Implemented in:** `graph/error_boundary.py` — `@node_error_boundary` decorator applied to all nodes; routing checks in `graph/workflow.py`.

---

## Orchestration and Loop Layer

### EC-14: Infinite review loop

**Scenario:** The Developer and Reviewer cycle forever without converging.

**Impact:** CRITICAL — the task never finishes.

**Resolution (HANDLED):** A hard cap of 3 iterations. At the cap, the workflow ends with the best version produced so far.

**Implemented in:** `agents/supervisor.py` — iteration counter and cap.

### EC-15: Oscillation (no progress across iterations)

**Scenario:** Each iteration fixes one issue and introduces another; the issue count never decreases.

**Impact:** IMPORTANT — iterations are wasted.

**Resolution (HANDLED):** A loop circuit breaker tracks `issue_count` per iteration. If the count does not decrease for two consecutive iterations, the loop is abandoned early and the workflow ends with the best version seen.

**Implemented in:** `agents/supervisor.py` — `issue_count_history` tracking.

### EC-16: State context overflow

**Scenario:** By iteration 3, the accumulated state makes the prompt too large for a 7B model's effective context window.

**Impact:** IMPORTANT — degraded model quality, possible truncation.

**Resolution (HARDENED):** A formal **state-trimming rule**: each node receives only the state fields it needs, never the full message history. The Developer on a retry receives the current code and the current feedback only — not prior iterations, not the raw message log. State carries structured fields, not a growing transcript.

**Implemented in:** Each agent node selects required fields explicitly; `graph/state.py` keeps no unbounded message list.

### EC-17: Supervisor cannot decide

**Scenario:** The Supervisor receives ambiguous input.

**Impact:** MINOR.

**Resolution (HANDLED):** The Supervisor decision logic is a deterministic decision tree, not an LLM judgment call. Every input maps to exactly one branch (loop, end-success, end-warnings, end-failed).

**Implemented in:** `agents/supervisor.py` — deterministic routing function.

---

## Pipeline Layer

### EC-18: One task fails in a parallel pipeline batch

**Scenario:** Three tasks run via `abatch`; one raises an exception.

**Impact:** CRITICAL — by default the first failure cancels the entire batch.

**Resolution (PLANNED):** A future batch runner should invoke the compiled workflow with `abatch(..., return_exceptions=True)`. The current UI runs one task at a time, so this failure mode is outside the implemented surface.

**Implemented in:** Not implemented yet; planned extension point.

### EC-19: Workspace collision between parallel tasks

**Scenario:** Two pipeline tasks write to the same files.

**Impact:** CRITICAL — tasks overwrite each other's output.

**Resolution (HANDLED):** Each task gets an isolated directory, `workspace/task-{id}/`, and an isolated local git branch, `feat/task-{id}`, inside that generated task repository.

**Implemented in:** `graph/nodes.py`, `graph/integrator.py`, MCP filesystem server scoping.

### EC-20: Shared-state corruption between parallel tasks

**Scenario:** Parallel tasks interfere through shared mutable state.

**Impact:** CRITICAL.

**Resolution (HANDLED):** LangGraph state is per-invocation. Each task carries its own state object, and agents are stateless wrappers around prompts and schemas. `LLMPool` has small mutable health/failure counters; current UI execution is single-task, and future parallel batch execution should revisit synchronization if multiple workflows share one pool.

**Implemented in:** `graph/state.py`, `llm/pool.py`.

---

## Tools, MCP, and Git Layer

### EC-21: Path traversal attempt

**Scenario:** An agent tries to write outside the workspace (`../../etc/passwd`).

**Impact:** CRITICAL — security.

**Resolution (HANDLED):** The MCP filesystem server resolves every path and verifies it stays within the allowed workspace root. Out-of-bounds paths are rejected.

**Implemented in:** MCP filesystem server configuration; see `docs/security/security-guidelines.md`.

### EC-22: Forbidden shell command

**Scenario:** An agent attempts `rm`, `curl`, or `sudo`.

**Impact:** CRITICAL — security.

**Resolution (HANDLED):** The workspace MCP server exposes only a bounded `run_pytest` tool for command execution. It does not accept arbitrary shell commands from agents.

**Implemented in:** `mcp_servers/workspace_server.py`.

### EC-23: MCP server crashes mid-task

**Scenario:** An MCP server process dies while an agent is using it.

**Impact:** IMPORTANT — tool calls fail.

**Resolution (PARTIAL):** MCP tool failures propagate to the node layer and are caught by the node error boundary, producing a FAILED workflow with `node_error`. The current MCP client does not implement reconnect.

**Implemented in:** `tools/mcp_client.py`, `graph/error_boundary.py`.

### EC-24: Disk full or file write fails

**Scenario:** Writing generated code fails because the disk is full or permissions are wrong.

**Impact:** IMPORTANT.

**Resolution (HANDLED):** File-write failures propagate out of the MCP tool call and are caught by the node error boundary. The workflow ends with FAILED status and a clear `node_error` rather than crashing the process.

**Implemented in:** `mcp_servers/workspace_server.py`, `tools/mcp_client.py`, `graph/error_boundary.py`.

### EC-25: Git not initialized or branch already exists

**Scenario:** The Integrator runs in generated-code mode but the workspace is not a git repository, or the target branch name is taken.

**Impact:** IMPORTANT — the commit step fails.

**Resolution (HARDENED):** In generated-code mode, the Integrator asks the workspace MCP server to initialize a git repository if needed, choose the target feature branch or the next available numeric suffix, add a generated `.gitignore`, and commit. The git tool returns structured commit metadata (`committed`, `branch`, `message`) and the Integrator writes it back into workflow state. A failed commit returns `committed: false` with a clear message. In Project Mode, the Integrator does not commit or push; it produces a diff preview and only writes selected-folder files after explicit apply.

**Implemented in:** `graph/integrator.py`, `mcp_servers/workspace_server.py`.

---

## RAG and UI Layer

### EC-26: ChromaDB is empty (ingestion never ran)

**Scenario:** The RAG vector store has no documents because `rag/ingest.py` was never run.

**Impact:** CRITICAL — agents may crash when retrieval returns nothing, or silently lose all standards context.

**Resolution (HANDLED):** The retriever degrades gracefully: if the collection is empty or unavailable, retrieval returns an empty result with status metadata and agents proceed with no RAG context. The workflow records `rag_status`, `rag_message`, and `rag_chunk_count`; the UI shows whether RAG was retrieved, empty, disabled, or unavailable. There is no blocking startup check.

**Implemented in:** `rag/retriever.py`, `graph/nodes.py`, `ui/streamlit_app.py`.

### EC-27: Embedding model unavailable

**Scenario:** The `nomic-embed-text` model is not pulled, so embeddings cannot be computed.

**Impact:** IMPORTANT — RAG cannot function.

**Resolution (HANDLED):** Embedding failures are caught inside retrieval and converted to empty RAG context. The system still runs without RAG. There is no separate startup model check in the current UI.

**Implemented in:** `rag/retriever.py`.

### EC-28: Empty or malformed user input

**Scenario:** The user submits an empty task or whitespace.

**Impact:** IMPORTANT — the workflow runs on nothing.

**Resolution (HARDENED):** Input is validated at the UI boundary before the workflow starts. Empty or whitespace-only input is rejected with an inline error message; the workflow is not invoked. In Project Mode, non-empty chat first passes through the Project Chat Router; direct conversation/help/status/clarify routes are answered without starting Project Intake, Developer, Reviewer, QA, file writes, commits, or pushes.

**Implemented in:** `ui/streamlit_app.py`, `graph/project_chat_intent.py`, `agents/project_chat_router.py`, `agents/project_chat_responder.py`.

### EC-29: UI disconnects mid-task

**Scenario:** The user closes the browser tab while a workflow is running.

**Impact:** MINOR — acceptable for a single-user demo system.

**Resolution (PLANNED):** The current single-user demo does not add explicit disconnect recovery beyond standard Streamlit behavior. A production version should persist in-flight run state and allow reconnect/resume.

**Implemented in:** Not implemented beyond standard Streamlit behavior.

---

## Resolution Summary

| ID | Severity | Status | Key Mechanism |
|----|----------|--------|---------------|
| EC-01 | IMPORTANT | PARTIAL | Warm-up health marking + fallback routing support |
| EC-02 | IMPORTANT | HANDLED | Retry + circuit breaker |
| EC-03 | CRITICAL | PARTIAL | Degraded state + UI banner when fallback is possible/configured |
| EC-04 | IMPORTANT | HARDENED | Warm-up phase |
| EC-05 | CRITICAL | HANDLED | NUM_PARALLEL=1, model sizing |
| EC-07 | CRITICAL | HARDENED | Structured output + retry + fallback plan |
| EC-08 | CRITICAL | HARDENED | Structured output + file validation + retry |
| EC-09 | IMPORTANT | HANDLED | Review loop |
| EC-10 | CRITICAL | HARDENED | Structured output + retry + fail-closed error boundary |
| EC-11 | CRITICAL | HARDENED | Subprocess timeout on test execution |
| EC-12 | IMPORTANT | HANDLED | pytest error capture |
| EC-13 | CRITICAL | HARDENED | Node error boundary decorator |
| EC-14 | CRITICAL | HANDLED | Max iteration cap |
| EC-15 | IMPORTANT | HANDLED | Loop circuit breaker |
| EC-16 | IMPORTANT | HARDENED | State-trimming rule |
| EC-17 | MINOR | HANDLED | Deterministic decision tree |
| EC-18 | CRITICAL | PLANNED | Future abatch runner with return_exceptions=True |
| EC-19 | CRITICAL | HANDLED | Per-task workspace + branch |
| EC-20 | CRITICAL | HANDLED | Immutable per-task state |
| EC-21 | CRITICAL | HANDLED | Workspace path validation |
| EC-22 | CRITICAL | HANDLED | Only bounded pytest tool exposed |
| EC-23 | IMPORTANT | PARTIAL | MCP failures caught by node boundary |
| EC-24 | IMPORTANT | HANDLED | File-write failures become node errors |
| EC-25 | IMPORTANT | HARDENED | Generated-code git init/branch suffix/commit metadata; Project Mode preview/apply |
| EC-26 | CRITICAL | HANDLED | RAG graceful degradation + UI status |
| EC-27 | IMPORTANT | HANDLED | Embedding failures degrade to empty RAG |
| EC-28 | IMPORTANT | HARDENED | UI input validation + Project Chat routing gate |
| EC-29 | MINOR | PLANNED | Explicit reconnect/resume support |

Statuses reflect the current repository implementation. Planned items are
kept in the register so they remain visible as future work rather than being
presented as already complete.
