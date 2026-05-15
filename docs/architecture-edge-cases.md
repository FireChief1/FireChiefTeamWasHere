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

---

## Infrastructure and Network Layer

### EC-01: A worker PC is down at startup

**Scenario:** PC1 or PC2 is powered off or unreachable when the system starts.

**Impact:** IMPORTANT — one capability (CODER or REASONER) has no primary node.

**Resolution (HANDLED):** The `LLMPool` runs a health check before the workflow begins. An unreachable node is marked unhealthy. Requests for its capability fall back to the Mac fallback node (`qwen2.5:3b`).

**Implemented in:** `llm/pool.py` — `health_check_loop`, `pick_node`.

### EC-02: A worker PC crashes mid-task

**Scenario:** A PC becomes unreachable while an agent is calling it.

**Impact:** IMPORTANT — an in-flight request fails.

**Resolution (HANDLED):** Retry with exponential backoff (`tenacity`). After 3 consecutive failures the node's circuit breaker opens and routing skips it. The request is retried against another healthy node or the fallback.

**Implemented in:** `llm/pool.py` — `generate` with retry decorator, circuit breaker state per node.

### EC-03: Both worker PCs are down (DEGRADED MODE)

**Scenario:** Neither PC1 nor PC2 is reachable. Only the Mac fallback is available.

**Impact:** CRITICAL — the whole CODER/REASONER topology is gone.

**Resolution (HARDENED):** The system enters **DEGRADED MODE** instead of failing. All capabilities route to the Mac fallback node (`qwen2.5:3b`). Quality drops because a 3B model is weaker, but the demo continues. The UI shows a persistent yellow banner: "Worker PCs unreachable — running in fallback mode." DEGRADED MODE is logged and surfaced in the final result metadata.

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

**Resolution (HARDENED):** The Analyst node validates its own output. If the plan is empty or has zero usable steps, it retries the LLM call once with a stricter prompt. If the retry also fails, the node degrades gracefully: it sets a single-step plan that instructs the Developer to work directly from the original task description. The workflow never stalls on a bad plan.

**Implemented in:** `agents/analyst.py` — internal validation and one-shot retry; graceful fallback plan.

### EC-08: Developer output cannot be parsed

**Scenario:** The Developer returns prose, partial code, or a broken structured response instead of valid code.

**Impact:** CRITICAL — there is no code to review or test.

**Resolution (HARDENED):** Three-layer recovery:
1. LangChain `with_structured_output()` constrains the response to a Pydantic schema.
2. On a parse failure, the call is retried once with an explicit "return only valid code" instruction.
3. As a last resort, a regular expression extracts fenced code blocks from the raw text.

If all three fail, the Developer node sets `node_error` and the workflow routes to a FAILED end state with an honest report.

**Implemented in:** `agents/developer.py` — structured output, retry, regex fallback.

### EC-09: Developer writes code unrelated to the task

**Scenario:** The generated code compiles but does not solve the stated problem.

**Impact:** IMPORTANT — wrong solution.

**Resolution (HANDLED):** The Reviewer checks functional correctness against the original task and reports a BLOCKER. The Supervisor routes back to the Developer with that feedback. This is the normal review loop.

**Implemented in:** `agents/reviewer.py`, `agents/supervisor.py`.

### EC-10: Reviewer feedback is malformed JSON

**Scenario:** The Reviewer (a 7B model) emits broken JSON, so the Supervisor cannot parse the feedback.

**Impact:** CRITICAL — the Supervisor cannot make a routing decision.

**Resolution (HARDENED):** Three-layer recovery:
1. `with_structured_output()` constrains the Reviewer to a Pydantic feedback schema.
2. On a parse failure, retry once asking explicitly for valid JSON.
3. If still unparseable, the system fails safe: it synthesizes a single feedback item — `severity: BLOCKER, issue: "review output could not be parsed"` — which forces a loop iteration rather than wrongly approving the code.

Failing safe means an unparseable review never results in code being approved.

**Implemented in:** `agents/reviewer.py` — structured output, retry, safe-fallback feedback.

### EC-11: Generated code contains an infinite loop and hangs pytest

**Scenario:** The Developer produces code with an infinite loop; the QA agent runs `pytest`, which never returns.

**Impact:** CRITICAL — the entire system freezes.

**Resolution (HARDENED):** Every test execution runs under a hard subprocess timeout (`subprocess.run(..., timeout=30)`). On timeout, the process is killed and the QA agent reports a failing test: `"test execution timed out — possible infinite loop"`. This becomes feedback and triggers a loop iteration.

**Implemented in:** `agents/qa.py` — subprocess timeout; MCP shell server also enforces a per-command timeout.

### EC-12: Generated code has a syntax error

**Scenario:** The code does not even parse.

**Impact:** IMPORTANT — tests cannot run.

**Resolution (HANDLED):** `pytest` reports a collection error. The QA agent captures it as a failing result and reports it as feedback. The review loop sends it back to the Developer.

**Implemented in:** `agents/qa.py`.

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

**Resolution (HARDENED):** The pipeline invokes `abatch` with `return_exceptions=True`. Each task is isolated: a failure in one task is captured as a result for that task only, and the other tasks complete normally. The UI shows per-task status.

**Implemented in:** `graph/pipeline.py` — `abatch(..., return_exceptions=True)`.

### EC-19: Workspace collision between parallel tasks

**Scenario:** Two pipeline tasks write to the same files.

**Impact:** CRITICAL — tasks overwrite each other's output.

**Resolution (HANDLED):** Each task gets an isolated directory, `workspace/task-{id}/`, and an isolated git branch, `feat/task-{id}`.

**Implemented in:** `graph/pipeline.py`, MCP filesystem server scoping.

### EC-20: Shared-state corruption between parallel tasks

**Scenario:** Parallel tasks interfere through shared mutable state.

**Impact:** CRITICAL.

**Resolution (HANDLED):** LangGraph state is immutable and per-invocation. Each task carries its own state object. Agents are stateless functions. The only shared component, `LLMPool`, is read-mostly and guards its mutable fields with an `asyncio.Lock`.

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

**Resolution (HANDLED):** The MCP shell server enforces a command allow-list (`pytest`, `ruff`, `mypy`). Everything else is rejected.

**Implemented in:** MCP shell server configuration.

### EC-23: MCP server crashes mid-task

**Scenario:** An MCP server process dies while an agent is using it.

**Impact:** IMPORTANT — tool calls fail.

**Resolution (HARDENED):** MCP tool calls are wrapped in try/except. A tool failure is converted into a structured error returned to the agent ("file write failed"), which the agent surfaces as feedback. The node error boundary (EC-13) catches anything unhandled. The MCP client attempts one reconnect before giving up.

**Implemented in:** `tools/mcp_client.py` — error wrapping and single reconnect.

### EC-24: Disk full or file write fails

**Scenario:** Writing generated code fails because the disk is full or permissions are wrong.

**Impact:** IMPORTANT.

**Resolution (HARDENED):** File-write tool calls catch `OSError`. The failure is reported to the Developer agent as an error result and ultimately, if unrecoverable, ends the task with a FAILED status and a clear message rather than a crash.

**Implemented in:** `tools/mcp_client.py`, node error boundary.

### EC-25: Git not initialized or branch already exists

**Scenario:** The Integrator runs but the workspace is not a git repository, or the target branch name is taken.

**Impact:** IMPORTANT — the commit step fails.

**Resolution (HARDENED):** The Integrator checks for a git repository and runs `git init` if needed. If the target branch already exists, it appends a numeric suffix (`feat/task-1-2`). All git operations are checked; a git failure ends the task with COMPLETED_WITH_WARNINGS (the code is still valid, only the commit step failed) rather than crashing.

**Implemented in:** `graph/integrator.py`.

---

## RAG and UI Layer

### EC-26: ChromaDB is empty (ingestion never ran)

**Scenario:** The RAG vector store has no documents because `rag/ingest.py` was never run.

**Impact:** CRITICAL — agents may crash when retrieval returns nothing, or silently lose all standards context.

**Resolution (HARDENED):** Two parts:
1. A startup check verifies the collection is non-empty; if empty, the UI shows a warning: "RAG knowledge base is empty — run ingestion."
2. The retriever degrades gracefully: if retrieval returns no chunks, agents proceed with an empty context string instead of crashing. A log entry records "generation without RAG context."

**Implemented in:** `rag/retriever.py` — empty-result handling; startup check in `ui/streamlit_app.py`.

### EC-27: Embedding model unavailable

**Scenario:** The `nomic-embed-text` model is not pulled, so embeddings cannot be computed.

**Impact:** IMPORTANT — RAG cannot function.

**Resolution (HARDENED):** Startup check confirms the embedding model is available via Ollama. If missing, the UI shows actionable instructions (`ollama pull nomic-embed-text`). The system still runs without RAG (graceful degradation per EC-26).

**Implemented in:** Startup check in `ui/streamlit_app.py`.

### EC-28: Empty or malformed user input

**Scenario:** The user submits an empty task or whitespace.

**Impact:** IMPORTANT — the workflow runs on nothing.

**Resolution (HARDENED):** Input is validated at the UI boundary before the workflow starts. Empty or whitespace-only input is rejected with an inline error message; the workflow is not invoked.

**Implemented in:** `ui/streamlit_app.py` — input validation.

### EC-29: UI disconnects mid-task

**Scenario:** The user closes the browser tab while a workflow is running.

**Impact:** MINOR — acceptable for a single-user demo system.

**Resolution (HANDLED):** The workflow continues to completion server-side. Streamlit session state holds the result; on reconnect within the session, the result is still available. No special handling beyond standard Streamlit behavior is required for the demo scope.

**Implemented in:** Standard Streamlit session behavior.

---

## Resolution Summary

| ID | Severity | Status | Key Mechanism |
|----|----------|--------|---------------|
| EC-01 | IMPORTANT | HANDLED | Health check + fallback routing |
| EC-02 | IMPORTANT | HANDLED | Retry + circuit breaker |
| EC-03 | CRITICAL | HARDENED | Degraded mode + UI banner |
| EC-04 | IMPORTANT | HARDENED | Warm-up phase |
| EC-05 | CRITICAL | HANDLED | NUM_PARALLEL=1, model sizing |
| EC-07 | CRITICAL | HARDENED | Plan validation + graceful fallback |
| EC-08 | CRITICAL | HARDENED | Structured output + retry + regex |
| EC-09 | IMPORTANT | HANDLED | Review loop |
| EC-10 | CRITICAL | HARDENED | Structured output + retry + fail-safe BLOCKER |
| EC-11 | CRITICAL | HARDENED | Subprocess timeout on test execution |
| EC-12 | IMPORTANT | HANDLED | pytest error capture |
| EC-13 | CRITICAL | HARDENED | Node error boundary decorator |
| EC-14 | CRITICAL | HANDLED | Max iteration cap |
| EC-15 | IMPORTANT | HANDLED | Loop circuit breaker |
| EC-16 | IMPORTANT | HARDENED | State-trimming rule |
| EC-17 | MINOR | HANDLED | Deterministic decision tree |
| EC-18 | CRITICAL | HARDENED | abatch return_exceptions=True |
| EC-19 | CRITICAL | HANDLED | Per-task workspace + branch |
| EC-20 | CRITICAL | HANDLED | Immutable per-task state |
| EC-21 | CRITICAL | HANDLED | Workspace path validation |
| EC-22 | CRITICAL | HANDLED | Shell command allow-list |
| EC-23 | IMPORTANT | HARDENED | MCP error wrapping + reconnect |
| EC-24 | IMPORTANT | HARDENED | OSError handling |
| EC-25 | IMPORTANT | HARDENED | Git init check + branch suffix |
| EC-26 | CRITICAL | HARDENED | RAG graceful degradation + startup check |
| EC-27 | IMPORTANT | HARDENED | Embedding model startup check |
| EC-28 | IMPORTANT | HARDENED | UI input validation |
| EC-29 | MINOR | HANDLED | Standard Streamlit session |

**Totals:** 28 edge cases — 13 HANDLED by the base architecture, 15 HARDENED with specific mechanisms added.
