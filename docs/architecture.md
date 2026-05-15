# System Architecture

This document describes the architecture of the multi-agent code development system. It is the revised design that incorporates the resilience mechanisms identified in `architecture-edge-cases.md`.

The system simulates a software development team using local LLMs. Specialized agents (Analyst, Developer, Reviewer, QA) collaborate under an orchestrator to turn a task description into reviewed, tested code.

## Design Goals

1. **Distributed** — run LLM inference across heterogeneous local hardware.
2. **Resilient** — degrade gracefully; never crash silently.
3. **Pipelined** — process multiple tasks with overlapping stages for throughput.
4. **Zero-cost** — fully local, open-source, no paid APIs.

## Physical Topology

Deployment topology is configuration, not architecture. The system runs on one, two, or three machines without code changes, because the LLM pool routes by capability rather than by machine.

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

If the core works and time permits, two Ubuntu PCs (RTX 3050 6 GB each) can be added to the pool as extra nodes. This is a configuration change — the `LLMPool` code does not change — and it makes pipeline parallelism yield a real speedup.

```
        LAN (Gigabit)
   ┌──────────┬──────────┬──────────┐
   ▼          ▼          ▼
 Mac        PC1        PC2
 orchestr.  CODER      REASONER
 +FALLBACK  qwen2.5-   qwen2.5:7b-
            coder:7b   instruct
```

All LLMs are from the Qwen2.5 family (Apache 2.0). In the single-machine core, pipeline parallelism provides task concurrency but no speedup, because one model serializes inference; the speedup applies only in the scale-out deployment.

## Software Layers

The orchestrator software is organized in five layers. Each layer calls only the layer below it.

```
┌────────────────────────────────────────────────────┐
│ PRESENTATION   Streamlit UI                         │
│                chat, pipeline grid, agent activity, │
│                GPU dashboard, push button           │
├────────────────────────────────────────────────────┤
│ ORCHESTRATION  LangGraph workflow                   │
│                StateGraph, nodes, conditional edges,│
│                abatch pipeline, error boundary      │
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
                  │   WARM-UP        │  EC-04: load models into VRAM
                  │   health check   │  EC-26/27: verify RAG + embeddings
                  └────────┬─────────┘
                           ▼
                  ┌──────────────────┐
                  │   ANALYST        │  EC-07: validates own plan,
                  │   (REASONER)     │  retries once, degrades gracefully
                  └────────┬─────────┘
                           ▼
                  ┌──────────────────┐
                  │   DEVELOPER      │  EC-08: structured output + retry
                  │   (CODER)        │  + regex fallback
                  │   RAG + MCP write│  EC-26: proceeds if RAG empty
                  └────────┬─────────┘
                           ▼
                ╔══════════════════════╗
                ║  PARALLEL (Send())   ║
                ╠══════════╦═══════════╣
                ▼          ▼
        ┌───────────┐ ┌───────────┐
        │ REVIEWER  │ │    QA     │  EC-11: pytest under
        │ (CODER)   │ │(REASONER) │  subprocess timeout
        │ EC-10:    │ │           │
        │ fail-safe │ │           │
        │ JSON      │ │           │
        └─────┬─────┘ └─────┬─────┘
              └──────┬──────┘
                     ▼
            ┌──────────────────┐
            │   SUPERVISOR     │  deterministic decision tree
            │   (deterministic)│  EC-14: max 3 iterations
            └────────┬─────────┘  EC-15: oscillation breaker
                     │
        ┌────────────┼────────────┬──────────────┐
        ▼            ▼            ▼              ▼
   ┌─────────┐ ┌──────────┐ ┌──────────┐  ┌───────────┐
   │ loop →  │ │ SUCCESS  │ │ WARNINGS │  │  FAILED   │
   │Developer│ │    ↓     │ │    ↓     │  │  (best    │
   └─────────┘ │INTEGRATOR│ │   END    │  │  version) │
               └────┬─────┘ └──────────┘  └───────────┘
                    ▼
              ┌──────────┐
              │   END    │  EC-25: git init check,
              │ + commit │  branch suffix on conflict
              └──────────┘

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

`LLMPool` routes by capability (CODER, REASONER, FALLBACK), not by round-robin. Each node has a health state and a circuit breaker. When no specialized node is healthy for a capability, the pool routes to the Mac fallback and the system enters DEGRADED MODE — lower quality but still running, with a visible UI banner. (EC-01, EC-02, EC-03)

### Warm-Up Phase

Before the workflow starts, a warm-up step sends a trivial prompt to each node so models are resident in VRAM, and verifies that ChromaDB and the embedding model are available. This eliminates cold-start timeouts and surfaces missing-dependency problems immediately. (EC-04, EC-26, EC-27)

### Structured Output with Fail-Safe Fallback

Agents that must return structured data (Developer code, Reviewer feedback) use `with_structured_output()`, retry once on a parse failure, and then fall back: the Developer extracts code via regex; the Reviewer synthesizes a BLOCKER feedback item so unparseable reviews never approve code. Failing safe always favors another loop iteration over a wrong approval. (EC-08, EC-10)

### Bounded Test Execution

The QA agent runs all generated tests under a hard subprocess timeout. A hanging test (for example, an infinite loop in generated code) is killed and reported as a failing test, which feeds the review loop instead of freezing the system. (EC-11)

### Bounded Review Loop

The Supervisor caps the Developer-Reviewer loop at 3 iterations and abandons it early if the issue count does not decrease across two iterations. At termination it returns the best version produced, not necessarily the last one, with an honest status: SUCCESS, COMPLETED_WITH_WARNINGS, or FAILED. (EC-14, EC-15)

### State Trimming

State carries structured fields, not a growing message transcript. Each node receives only the fields it needs. A Developer retry sees the current code and current feedback only — never the full history — which keeps prompts within a 7B model's effective context window. (EC-16)

### Graceful RAG Degradation

If the RAG knowledge base is empty or retrieval returns nothing, agents proceed with an empty context string and log the event. Missing RAG degrades quality but never crashes the workflow. (EC-26)

## Data Flow: The State Object

A single `AgentState` object flows through the workflow, growing as each node contributes. The state is immutable per invocation — each node returns a new state — which guarantees task isolation in the parallel pipeline.

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

Background: health_check_loop every 15s probes all nodes,
updates health state, auto-recovers nodes that come back.
```

## Pipeline Parallelism

Multiple tasks are submitted together via LangGraph's `abatch`, invoked with `return_exceptions=True` so one task's failure never aborts the batch. Because agents for different stages run on different machines, tasks at different stages execute truly in parallel.

```
        t1        t2        t3        t4
Task1: [Analyst][Develop][Rev+QA ][Super]
Task2:          [Analyst][Develop][Rev+QA]
Task3:                   [Analyst][Develop]

At t2: PC2 runs Task1.Developer's reasoning peers while
PC1 runs Task1.Developer — both GPUs busy.
```

Each task uses an isolated workspace (`workspace/task-{id}/`) and an isolated git branch (`feat/task-{id}`), so parallel tasks never collide. (EC-18, EC-19, EC-20)

## Git and Remote Push

Agents perform local git operations (add, commit, branch, diff) through the MCP git tool. No agent pushes to a remote on its own.

After a SUCCESS result, the deterministic Integrator node creates a feature branch and a local commit (the commit message is LLM-generated in Conventional Commits style). Pushing to the remote is a separate, human-gated action: the UI presents a push button, and the user approves it. Pushes go only to feature branches, never to main. FAILED tasks never reach the Integrator.

## Tool Execution Model

Agents do not use native LLM tool-calling. A Day-2 reliability spike showed
that the core model produces valid structured output with 100% reliability
but emits valid native tool calls with 0% reliability. The architecture
therefore uses a structured-output-driven tool execution model.

```
LLM agent  ──►  structured output      (the DECISION: what to do)
                (Pydantic schema, 100% reliable)
                       │
                       ▼
Deterministic node  ──►  MCP tool call  (the ACTION: do it)
                         (plain Python, 100% reliable)
```

The agent decides what should happen and returns it as structured data. The
node — deterministic code — performs the action through an MCP tool. For
example, the Developer agent returns a `CodeOutput` schema; the Developer
node then calls the MCP filesystem tool to write each file. The QA agent
returns test code; the QA node runs it through the MCP shell tool.

This is more reliable than native tool-calling on local models and keeps the
decision (LLM) and the action (deterministic code) cleanly separated. MCP
remains the tool layer; only the caller changed from the LLM to node code.

## Technology Mapping

| Technology | Where it is used |
|-----------|------------------|
| LangGraph | Workflow orchestration, state machine, conditional edges, abatch |
| LangChain | Agent prompts, structured output, LLM calls |
| MCP | Filesystem, git, and shell tools, invoked by node code |
| RAG (ChromaDB) | Retrieval of coding standards and examples as agent context |

## Related Documents

- `architecture-edge-cases.md` — the failure-mode register this design hardens against
- `coding-standards/` — the standards agents follow and reviewers enforce
- `security/security-guidelines.md` — the security rules built into the MCP layer
