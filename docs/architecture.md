# System Architecture

This document describes the architecture of the multi-agent code development system. It is the revised design that incorporates the resilience mechanisms identified in `architecture-edge-cases.md`.

The system simulates a software development team using local LLMs. Specialized agents (Analyst, Developer, Reviewer, QA) collaborate under an orchestrator to turn a task description into reviewed, tested code. Project Mode adds a target project folder, project intake, unified diff previews, and an explicit apply button so agents can reason with project-level context without silently changing the selected folder.

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
| Project Chat Router | LLM router + policy | Decide whether a Project Mode chat message should be answered directly or sent into the workflow |
| Project Chat Responder | LLM agent | Answer direct chat/help/status/clarify messages without starting Developer/QA |
| Project Intake | Deterministic node | Read-only repository scan for Project Mode |
| Project Brief | Deterministic node | Detect stack, entrypoints, test commands, and risks |
| Project Registry | Service | Persist projects and checkpoints in Postgres |
| Task Classifier | Deterministic node | Select task profile: Python, Static Web, Docs, Project |
| Analyst | LLM agent | Break the task into a structured plan |
| Routed Developer | LLM agent | Use the profile-specific developer persona |
| Routed Reviewer | LLM agent | Use the profile-specific reviewer persona |
| Routed QA | LLM/deterministic node | Run profile-specific validation |
| Supervisor | Deterministic node | Decide: loop, finish, or fail |
| Integrator | Deterministic node | Create branch and local commit on success |
| LLMPool | Service | Route requests to healthy nodes by capability |
| RAG Retriever | Service | Provide relevant standards/examples as context |
| MCP Manager | Service | Expose filesystem, git, and shell tools |

The Supervisor and Integrator are deterministic — they make no LLM judgment calls — which removes a class of failure modes (see `architecture-edge-cases.md`, EC-17).

## Workflow Graph (Revised with Resilience)

```
Project Mode chat first passes through the Project Chat Router. The router
uses the local model as the primary semantic classifier, then a deterministic
policy layer normalizes workflow flags and blocks low-confidence routes. Only
`project_analysis` and `implementation` intents enter the graph below.

                    ┌─────────────┐
                    │   START     │
                    └──────┬──────┘
                          ▼
                  ┌──────────────────┐
                  │ PROJECT INTAKE   │  read-only repo scan;
                  │                  │  no-op outside project mode
                  └────────┬─────────┘
                           ▼
                  ┌──────────────────┐
                  │ PROJECT BRIEF    │  stack, entrypoints,
                  │                  │  tests, risks
                  └────────┬─────────┘
                           ▼
                  ┌──────────────────┐
                  │ TASK CLASSIFIER  │  chooses python,
                  │                  │  static_web, docs, project
                  └────────┬─────────┘
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

### Project Chat Intent Routing

The Project Mode UI does not treat every message as a code task. The Project
Chat Router runs before LangGraph and returns one of six intents:
`conversation`, `help`, `status`, `project_analysis`, `implementation`, or
`clarify`. Natural-language intent classification is model-first: casual
Turkish/English, typos, and project-analysis phrasing are interpreted by the
local REASONER model through structured output rather than by a large phrase
table. A deterministic policy layer still handles non-semantic safety rules:
empty messages, invalid workflow flags, model failures, and confidence below
the product threshold. Direct routes are then answered by the Project Chat
Responder agent, which can talk about known project status/context but cannot
start Developer, Reviewer, QA, file writes, commits, or pushes. The UI exposes
the final route as compact metadata such as
`model: project_analysis, confidence: 0.84`.

### Warm-Up Phase

Before the workflow starts, a warm-up step sends a trivial prompt to each configured LLM node so models are resident in memory when possible. RAG and embedding failures are handled by the retriever's graceful-degradation path rather than by a blocking startup check. (EC-04, EC-26, EC-27)

### Structured Output with Fail-Safe Fallback

Agents that must return structured data use `with_structured_output()`. The Developer node validates the returned files, retries once if the output is empty, unsupported, or syntactically invalid, and then fails honestly if the second attempt is still unusable. Reviewer structured-output failures are caught by the node error boundary, producing a FAILED workflow rather than an accidental approval. (EC-08, EC-10)

The Analyst plan is also validated. Empty or whitespace-only plan steps are
discarded; if the plan is still empty after one retry, the workflow uses a
single fallback step that instructs the Developer to implement directly from
the task description. This keeps a weak plan from stalling the whole run.

### Bounded Test Execution

The QA node runs generated tests under a hard subprocess timeout. A hanging test is killed and reported as a failing test. A syntactically invalid test file, a run with no collected tests, or a skipped-only run is treated as a failure so the workflow never reports success without real test execution. (EC-11)

### Bounded Review Loop

The Supervisor caps the Developer-Reviewer loop at 3 iterations and abandons it early if the issue count does not decrease across two iterations. At termination it returns the best version produced, not necessarily the last one, with an honest status: SUCCESS, COMPLETED_WITH_WARNINGS, or FAILED. (EC-14, EC-15)

### State Trimming

State carries structured fields, not a growing message transcript. Each node receives only the fields it needs. A Developer retry sees the current code and current feedback only — never the full history — which keeps prompts within a 7B model's effective context window. (EC-16)

### Graceful RAG Degradation

If the RAG knowledge base is empty, unavailable, disabled, or returns nothing, agents proceed with an empty context string and the workflow records `rag_status`, `rag_message`, and `rag_chunk_count` for the UI. Missing RAG degrades quality but never crashes the workflow. (EC-26)

### Project Mode Intake

Project Mode accepts a `project_path` from the UI and starts with
deterministic Project Intake and Project Brief nodes. Project Intake uses MCP
tools scoped to that folder to list text-oriented files, search task-derived
focus terms, read `git status --short --branch`, and capture a bounded
`git diff --stat`. It writes `project_path`, `project_summary`,
`project_relevant_files`, `project_search_matches`, `project_git_status`,
`project_git_diff`, and `project_focus_terms` into state.

Project Brief then reads recognized manifests such as `package.json`,
`pyproject.toml`, `requirements.txt`, `Cargo.toml`, `go.mod`, `*.csproj`, and
Docker files. It writes `project_brief`, `project_stack`,
`project_entrypoints`, `project_test_commands`, `project_risks`, and
`project_brief_files` into state. Analyst, Developer, and Reviewer prompts
include this compact context so they reason from deterministic project facts
instead of only task text.

The sidebar uses a Postgres-backed Project Registry to store selected project
folders and their latest checkpoints. Opening a project updates
`last_opened_at`; completing a Project Mode run stores a checkpoint with the
task, status, profile, brief, planned/written files, diff preview state, and
test counts. It also appends a `project_timeline_events` row so the project has
a conversation timeline rather than only a flat summary. User prompts are saved
as `user_message` events and the workflow's composed response is saved as an
`assistant_message` event. The main Project Mode surface renders those messages
as a chat; Project Intake, Developer, Reviewer, QA, Supervisor, and Integrator
remain visible in a collapsed technical details panel for debugging. The
sidebar can rename or delete registry entries; deletion removes only Postgres
registry data through cascading foreign keys and never deletes files on disk.
Registry reads are wrapped in a short Streamlit cache and are cleared after
writes. The next run receives a compact `project_memory` block containing the
latest known brief, stack, test commands, risks, last task, recent checkpoints,
and recent timeline events.

On a successful Project Mode run, the Integrator is preview-only by default:
it records `integration_planned_files`, `integration_file_actions`, and a
unified `integration_diff`. The UI stores the pending apply payload in session
state and writes generated files only when the user clicks the apply button.
The write step uses the same MCP path boundary and records
`integration_written_files`. The Project Registry then marks the matching
checkpoint as applied and appends a `project_apply` timeline event. It does not
auto-commit or push the target project; those actions remain human-gated. The
generated-code mode continues to write into isolated `workspace/task-{id}/`
folders and create local commits there.

### Task Profiles

The workflow does not route only by programming language; it routes by
artifact profile. The deterministic Task Classifier currently selects:

- `python` — Python modules, pytest validation, Python reviewer standards.
- `static_web` — HTML/CSS/vanilla JS artifacts, static-web reviewer, and
  deterministic HTML/static asset validation.
- `docs` — Markdown/text documentation output, docs reviewer, and advisory QA
  that blocks source/artifact files.
- `project` — Project Mode analysis/recommendation output. This profile is
  deliberately advisory and accepts exactly `PROJECT_PROPOSAL.md` so an
  "analyze/propose" request cannot overwrite existing project artifacts.

This prevents static-web tasks from being forced through Python-only filename
validation or pytest. For example, "Basit HTML sayfası yaz" is routed to
`static_web`, can produce `index.html`, and is validated as a page rather than
as a Python module. Conversely, "Analyze this project and propose the next safe
improvement" is routed to `project`, where the Developer acts as a project
advisor and the QA node blocks source files such as `index.html`, `.css`, `.js`,
or `.py`.

### Domain-Aware RAG

RAG retrieval is biased by `task_profile`. Python tasks prefer
`coding-standards/`, `testing/`, `patterns/`, `security/`, and
`code-review/`. Static web tasks prefer `frontend/`, `security/`,
`project-mode/`, and `code-review/`. If no profile-specific chunks are found,
retrieval falls back to the nearest general matches.

## Data Flow: The State Object

A single `AgentState` object flows through the workflow, growing as each node contributes. The state is immutable per invocation — each node returns a state update rather than mutating a shared transcript.

```
AgentState fields:
  task              str            original task description
  mode              "generate"|"review"|"project"
  task_profile      "python"|"static_web"|"docs"|"project"
  task_profile_reason str          why the profile was selected
  project_path      str            selected project folder
  project_apply_changes bool       whether Project Mode may write files
  project_summary   str            read-only project intake summary
  project_files     list[str]      text-oriented repository files
  project_relevant_files list[str] selected files for agent context
  project_search_matches list[dict] task-related repository matches
  project_git_status str           git status snapshot
  project_git_diff   str           bounded git diff stat
  project_focus_terms list[str]    terms used for project search
  project_brief     str            deterministic project profile summary
  project_stack     list[str]      detected languages/frameworks/services
  project_entrypoints list[str]    likely run commands or primary files
  project_test_commands list[str]  likely automated test commands
  project_risks     list[str]      risks from files, git state, profile state
  project_brief_files list[str]    manifests/configs read for the brief
  project_memory    str            saved registry/checkpoint context
  plan              list[str]      from Analyst
  code              dict[str,str]  filename -> content, from Developer
  rag_context       list[str]      retrieved chunks
  rag_status        str            retrieved, empty, disabled, or unavailable
  rag_message       str            user-facing RAG status detail
  rag_chunk_count   int            retrieved chunk count
  review_feedback   list[Feedback] from Reviewer
  test_results      TestResults    from QA
  integration_message str          git commit result from Integrator
  integration_branch  str          local branch used by Integrator
  integration_committed bool       whether Integrator created a commit
  integration_target_path str      Project Mode folder written by Integrator
  integration_planned_files list[str] Project Mode files proposed for writing
  integration_file_actions list[dict] create/modify/unchanged per file
  integration_diff str             unified diff for Project Mode preview
  integration_written_files list[str] Project Mode files written
  integration_preview_only bool    true when Project Mode stopped before write
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
Project Intake -> Project Brief -> Task Classifier -> RAG -> Analyst -> Developer -> Reviewer -> QA -> Supervisor -> Integrator
```

For normal generated-code runs, Project Intake and Project Brief are no-ops. In
Project Mode they collect context from the selected `project_path` before RAG
and planning, and the Integrator previews generated file writes as a unified
diff. Generated task mode remains isolated under `workspace/task-{id}/`;
successful or warning-completed tasks are committed in that directory on
`feat/task-{id}`. If that branch already exists in the generated task
repository, the MCP git tool appends a numeric suffix such as
`feat/task-{id}-2`. A future batch runner can use LangGraph
`abatch(..., return_exceptions=True)` over the same compiled workflow, but
`app/graph/pipeline.py` and a multi-task UI are not part of the current
implementation.

## Git and Remote Push

Agents do not push to a remote. The deterministic Integrator writes final code through the workspace MCP server and asks that server to create a local git commit.

After a SUCCESS or COMPLETED_WITH_WARNINGS result, the Integrator creates `workspace/task-{id}/`, initializes a git repository there if needed, checks out `feat/task-{id}` or an available suffixed branch, writes a `.gitignore` for generated test artefacts, and commits the generated code and tests with a deterministic `feat:` subject derived from the task. The Integrator writes `integration_message`, `integration_branch`, and `integration_committed` back into workflow state for the UI. FAILED tasks never reach the Integrator.

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
| MCP | Filesystem, project search, git, and shell tools, invoked by node code |
| RAG (ChromaDB) | Retrieval of coding standards and examples as agent context |

## Related Documents

- `architecture-edge-cases.md` — the failure-mode register this design hardens against
- `coding-standards/` — the standards agents follow and reviewers enforce
- `security/security-guidelines.md` — the security rules built into the MCP layer
