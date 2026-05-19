# System Architecture

This document describes the architecture of the multi-agent code development system. It is the revised design that incorporates the resilience mechanisms identified in `architecture-edge-cases.md`.

The system simulates a software development team using local LLMs. Specialized agents (Analyst, Developer, Reviewer, QA) collaborate under an orchestrator to turn a task description into reviewed, tested code.

## Design Goals

1. **Local-first** — run LLM inference on local hardware.
2. **Resilient** — degrade gracefully; never crash silently.
3. **Extensible** — keep the LLM pool and workflow boundaries ready for future batch or scale-out execution.
4. **Zero-cost** — fully local, open-source, no paid APIs.

## Physical Topology

The current implementation is a single-machine core. The LLM pool routes by capability rather than by agent name, so additional nodes can be added in the pool factory as a focused extension.

### Core Deployment (single machine)

The core, demo-critical deployment runs entirely on one machine.

```
┌──────────────────────────────────────┐
│ MacBook Pro M4 Pro — 24 GB           │
│ EVERYTHING                            │
│                                       │
│ LangGraph orchestration               │
│ Streamlit UI                          │
│ ChromaDB (RAG)                        │
│ MCP servers (filesystem, shell, git)  │
│ Ollama → qwen2.5-coder:14b            │
│                                       │
│ Four agents = four personas of the    │
│ same model. CODER, REASONER and       │
│ FALLBACK capabilities all resolve to  │
│ this single node.                     │
└──────────────────────────────────────┘
```

An agent is defined by its system prompt (persona), its tools, the slice of state it reads, and its output schema — not by the model or machine it runs on. One model serving four personas is a complete multi-agent system.

### Optional Scale-Out (bonus)

If the core works and time permits, worker machines can be added to the pool as extra nodes. The current repository does not ship a multi-machine configuration UI; adding workers means extending `build_default_pool()` or adding configuration-driven node loading.

```
        LAN (Gigabit)
   ┌──────────┬──────────┬──────────┐
   ▼          ▼          ▼
 Mac        PC1        PC2
 orchestr.  CODER      REASONER
 +FALLBACK  qwen2.5-   qwen2.5:7b-
            coder:7b   instruct
```

All intended LLMs are from the Qwen2.5 family (Apache 2.0). In the single-machine core, one model serializes inference for all agent personas.

## Software Layers

The orchestrator software is organized in five layers. Each layer calls only the layer below it.

```
┌────────────────────────────────────────────────────┐
│ PRESENTATION   Streamlit UI                         │
│                task input, live agent activity,     │
│                run history, final result            │
├────────────────────────────────────────────────────┤
│ ORCHESTRATION  LangGraph workflow                   │
│                StateGraph, nodes, conditional edges,│
│                error boundary                       │
├────────────────────────────────────────────────────┤
│ AGENTS         Analyst, Developer, Reviewer, QA     │
│                + Supervisor, Integrator (nodes)     │
├────────────────────────────────────────────────────┤
│ SERVICES       LLMPool, RAG Retriever, MCP Manager  │
├────────────────────────────────────────────────────┤
│ INFRASTRUCTURE httpx pool, ChromaDB, MCP servers,   │
│                Ollama clients                       │
└────────────────────────────────────────────────────┘
```

## Component Roles

| Component | Type | Responsibility |
|-----------|------|----------------|
| Analyst | LLM agent | Break the task into a structured plan |
| Developer | LLM agent | Write code; fix code on review feedback |
| Reviewer | LLM agent | Inspect code quality, correctness, security |
| QA | LLM agent | Generate and run tests |
| Supervisor | Deterministic node | Decide: loop, finish, or fail |
| Integrator | Deterministic node | Create branch and local commit on success |
| LLMPool | Service | Route requests to healthy nodes by capability |
| RAG Retriever | Service | Provide relevant standards/examples as context |
| MCP Manager | Service | Expose filesystem, git, and shell tools |

The Supervisor and Integrator are deterministic — they make no LLM judgment calls — which removes a class of failure modes (see `architecture-edge-cases.md`, EC-17).

## Workflow Graph (Revised with Resilience)

```
                    ┌─────────────┐
                    │   START     │
                    └──────┬──────┘
                           ▼
                  ┌──────────────────┐
                  │   RAG            │  retrieves coding standards;
                  │                  │  empty retrieval is allowed
                  └────────┬─────────┘
                           ▼
                  ┌──────────────────┐
                  │   ANALYST        │  creates a short plan
                  │   (REASONER)     │
                  └────────┬─────────┘
                           ▼
                  ┌──────────────────┐
                  │   DEVELOPER      │  structured code output;
                  │   (CODER)        │  validates filenames and Python syntax
                  └────────┬─────────┘
                           ▼
                  ┌──────────────────┐
                  │   REVIEWER       │  structured review findings
                  │   (CODER)        │
                  └────────┬─────────┘
                           ▼
                  ┌──────────────────┐
                  │   QA             │  writes tests and runs pytest
                  │   (REASONER)     │  through MCP with timeout
                  └────────┬─────────┘
                           ▼
                  ┌──────────────────┐
                  │   SUPERVISOR     │  deterministic decision tree
                  │                  │  max iterations + no-progress stop
                  └────────┬─────────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
   loop to Developer   SUCCESS/WARNINGS    FAILED
                            │
                            ▼
                      ┌──────────┐
                      │INTEGRATOR│  writes final code and local commit
                      └────┬─────┘
                           ▼
                          END

CROSS-CUTTING — EC-13 ERROR BOUNDARY:
Every node is wrapped by @node_error_boundary. Any unhandled
exception is caught, logged, written to state.node_error, and
sets state.should_abort. All conditional edges check
should_abort first and route to a FAILED end state.
```

## The Resilience Layer

The revised architecture adds a cross-cutting resilience layer. These mechanisms are not a separate component; they are woven into existing nodes and services.

### Node Error Boundary

Every node function is wrapped by the `@node_error_boundary` decorator. It catches any unhandled exception, records a full traceback, writes the failure into `state.node_error`, and sets `state.should_abort = True`. The workflow then routes to a FAILED end state with an honest report. The system never crashes silently and never produces a green "success" on a hidden error. (EC-13)

### Capability Routing with Degraded Mode

`LLMPool` routes by capability (CODER, REASONER, FALLBACK), not by round-robin. Each node has a health state and a circuit breaker. If a configured specialized node is unavailable and a fallback node is usable, requests route to fallback. The Streamlit UI records and displays degraded mode when the current pool cannot serve every specialized capability. (EC-01, EC-02, EC-03)

### Warm-Up Phase

Before the workflow starts, a warm-up step sends a trivial prompt to each configured LLM node so models are resident in memory when possible. RAG and embedding failures are handled by the retriever's graceful-degradation path rather than by a blocking startup check. (EC-04, EC-26, EC-27)

### Structured Output with Fail-Safe Fallback

Agents that must return structured data use `with_structured_output()`. The Developer node validates the returned files, retries once if the output is empty, unsupported, or syntactically invalid, and then fails honestly if the second attempt is still unusable. Reviewer structured-output failures are caught by the node error boundary, producing a FAILED workflow rather than an accidental approval. (EC-08, EC-10)

### Bounded Test Execution

The QA node runs generated tests under a hard subprocess timeout. A hanging test is killed and reported as a failing test. A syntactically invalid test file, a run with no collected tests, or a skipped-only run is treated as a failure so the workflow never reports success without real test execution. (EC-11)

### Bounded Review Loop

The Supervisor caps the Developer-Reviewer loop at 3 iterations and abandons it early if the issue count does not decrease across two iterations. At termination it returns the best version produced, not necessarily the last one, with an honest status: SUCCESS, COMPLETED_WITH_WARNINGS, or FAILED. (EC-14, EC-15)

### State Trimming

State carries structured fields, not a growing message transcript. Each node receives only the fields it needs. A Developer retry sees the current code and current feedback only — never the full history — which keeps prompts within a 7B model's effective context window. (EC-16)

### Graceful RAG Degradation

If the RAG knowledge base is empty or retrieval returns nothing, agents proceed with an empty context string and log the event. Missing RAG degrades quality but never crashes the workflow. (EC-26)

## Data Flow: The State Object

A single `AgentState` object flows through the workflow, growing as each node contributes. The state is immutable per invocation — each node returns a state update rather than mutating a shared transcript.

```
AgentState fields:
  task              str            original task description
  mode              "generate"|"review"
  plan              list[str]      from Analyst
  code              dict[str,str]  filename -> content, from Developer
  rag_context       list[str]      retrieved chunks
  review_feedback   list[Feedback] from Reviewer
  test_results      TestResults    from QA
  iteration         int            current loop iteration
  issue_count_history  list[int]   for oscillation detection
  best_code         dict[str,str]  best version seen so far
  status            "SUCCESS"|"COMPLETED_WITH_WARNINGS"|"FAILED"
  node_error        str | None     set by the error boundary
  should_abort      bool           set by the error boundary
  is_degraded       bool           true if running on fallback only
```

## Capability-Aware LLM Pool

Agents never address a physical machine. They request a capability; the pool resolves it to a healthy node.

```
Agent: pool.generate(prompt, capability=CODER)
                 │
                 ▼
        ┌────────────────────┐
        │ filter healthy     │
        │ nodes for CODER    │
        └────────┬───────────┘
                 │
        ┌────────┴────────┐
        │ candidates?     │
        ├─────────────────┤
        │ yes → least-    │
        │ failed node     │
        │ no  → fallback  │ → sets is_degraded = true
        └────────┬────────┘
                 ▼
        ┌────────────────────┐
        │ httpx pooled POST  │
        │ retry + backoff    │
        │ circuit breaker    │
        └────────────────────┘

The pool exposes a health-check loop for long-running deployments. The current
Streamlit path performs warm-up before each run and surfaces degraded state in
the UI.
```

## Current Execution Model and Future Pipeline

The current UI runs one task at a time through the sequential graph:

```
RAG -> Analyst -> Developer -> Reviewer -> QA -> Supervisor -> Integrator
```

Generated task output is isolated under `workspace/task-{id}/`; successful or warning-completed tasks are committed in that directory on `feat/task-{id}`. A future batch runner can use LangGraph `abatch(..., return_exceptions=True)` over the same compiled workflow, but `app/graph/pipeline.py` and a multi-task UI are not part of the current implementation.

## Git and Remote Push

Agents do not push to a remote. The deterministic Integrator writes final code through the workspace MCP server and asks that server to create a local git commit.

After a SUCCESS or COMPLETED_WITH_WARNINGS result, the Integrator creates `workspace/task-{id}/`, initializes a git repository there if needed, checks out `feat/task-{id}`, writes a `.gitignore` for generated test artefacts, and commits the generated code and tests with a deterministic `feat:` subject derived from the task. FAILED tasks never reach the Integrator.

## Tool Execution Model

Agents do not use native LLM tool-calling in the workflow. The project keeps
LLM decisions in structured Pydantic outputs and lets deterministic node code
perform file, test, and git actions through MCP. This avoids depending on
local-model tool-call reliability for critical filesystem behavior.

```
LLM agent  ──►  structured output      (the DECISION: what to do)
                (Pydantic schema + validation)
                       │
                       ▼
Deterministic node  ──►  MCP tool call  (the ACTION: do it)
                         (plain Python + bounded MCP tools)
```

The agent decides what should happen and returns it as structured data. The
node — deterministic code — performs the action through an MCP tool. For
example, the Developer agent returns a `CodeOutput` schema; the QA and
Integrator nodes write the selected code into an isolated workspace before
running tests or creating the final local commit. The QA agent returns test
code; the QA node runs it through the MCP pytest tool.

This is more reliable than native tool-calling on local models and keeps the
decision (LLM) and the action (deterministic code) cleanly separated. MCP
remains the tool layer; only the caller changed from the LLM to node code.

## Technology Mapping

| Technology | Where it is used |
|-----------|------------------|
| LangGraph | Workflow orchestration, state machine, conditional edges |
| LangChain | Agent prompts, structured output, LLM calls |
| MCP | Filesystem, git, and shell tools, invoked by node code |
| RAG (ChromaDB) | Retrieval of coding standards and examples as agent context |

## Related Documents

- `architecture-edge-cases.md` — the failure-mode register this design hardens against
- `coding-standards/` — the standards agents follow and reviewers enforce
- `security/security-guidelines.md` — the security rules built into the MCP layer
