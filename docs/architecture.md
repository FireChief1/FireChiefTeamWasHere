# System Architecture

This document describes the architecture of the multi-agent code development system. It is the revised design that incorporates the resilience mechanisms identified in `architecture-edge-cases.md`.

The system simulates a software development team using local LLMs.
Specialized personas collaborate under a LangGraph orchestrator to turn a
task description into reviewed, tested code. Project Mode adds a chat-first
project workspace: a model-first Project Chat Router decides whether a message
should be answered directly or sent into the workflow, and Project Intake,
Project Brief, unified diff previews, and an explicit apply button let agents
reason with project-level context without silently changing the selected
folder. The presentation layer is migrating from a Streamlit-first interface
to a React + TypeScript + Vite workspace backed by a small local JSON API.

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
│ React/Vite UI + local JSON API        │
│ Streamlit legacy UI                   │
│ ChromaDB (RAG)                        │
│ MCP servers (filesystem, shell, git)  │
│ Ollama → qwen2.5:14b                  │
│        → qwen2.5-coder:14b            │
│        → qwen2.5vl:7b (lazy optional) │
│                                       │
│ CHAT resolves to the general model.   │
│ CODER, REASONER and FALLBACK resolve  │
│ to the coder-specialized model.       │
│ VISION resolves only when an image is  │
│ attached; it is not eagerly warmed.    │
└──────────────────────────────────────┘
```

An agent is defined by its system prompt (persona), its tools, the slice of
state it reads, and its output schema — not by the model or machine it runs
on. Multiple focused personas can share a configured local model when that is
the right tradeoff, but Project Chat is now separated from coding work through
the CHAT capability. Optional image/screenshot analysis is separated again
through VISION so the vision model never replaces the router or coder model.

### Optional Scale-Out (bonus)

If the core works and time permits, worker machines can be added to the pool as extra nodes. The current repository does not ship a multi-machine configuration UI; adding workers means extending `build_default_pool()` or adding configuration-driven node loading.

```
        LAN (Gigabit)
   ┌──────────┬──────────┬──────────┐
   ▼          ▼          ▼
 Mac        PC1        PC2
 orchestr.  CODER      REASONER
 CHAT       qwen2.5-   qwen2.5:7b-
 +FALLBACK  coder:7b   instruct
```

All intended generation LLMs are from the Qwen2.5 family (Apache 2.0). In the
single-machine core, `qwen2.5:14b` handles Project Chat routing/responses and
`qwen2.5-coder:14b` handles code workflow capabilities. `qwen2.5vl:7b` is an
optional lazy VISION node for attached images. If configured model tags are
identical, `build_default_pool()` groups those capabilities into one Ollama
node.

## Software Layers

The orchestrator software is organized in five layers. Each layer calls only the layer below it.

```
┌────────────────────────────────────────────────────┐
│ PRESENTATION   React/Vite Project UI                │
│                local JSON API, Streamlit legacy UI  │
│                project chat, timeline, diff detail  │
├────────────────────────────────────────────────────┤
│ ORCHESTRATION  LangGraph workflow                   │
│                StateGraph, nodes, conditional edges,│
│                error boundary                       │
├────────────────────────────────────────────────────┤
│ AGENTS         Chat Router/Responder, Analyst,      │
│                profile-routed Developer/Reviewer/QA │
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
| Project Chat Router | LLM router + safety policy | Decide whether a Project Mode chat message should be answered directly or sent into the workflow |
| Project Action Router | Registry + safety policy | Convert chat intent into concrete actions such as `path_info`, `read_file`, `list_folder`, `current_time`, `calculate`, `assistant_capabilities`, `analyze_project`, or `modify_project`; registered handlers validate and execute read-only actions |
| Project Chat Responder | LLM agent | Answer direct chat/help/status/clarify messages without starting Developer/QA |
| Project Intake | Deterministic node | Read-only repository scan for Project Mode |
| Project Brief | Deterministic node | Detect stack, entrypoints, test commands, and risks |
| Project Registry | Service | Persist projects and checkpoints in Postgres |
| React Project UI | Presentation | Project sidebar, chat timeline, router metadata, checkpoints, and technical result panels |
| Local JSON API | Presentation/API adapter | Serve project registry, folder browsing, and Project Chat workflow calls to the React UI without adding a Python web framework |
| Task Classifier | Deterministic node | Select task profile: Python, Static Web, Docs, Project |
| Analyst | LLM agent | Break the task into a structured plan |
| Routed Developer | LLM agent | Use the profile-specific developer persona |
| Routed Reviewer | LLM agent | Use the profile-specific reviewer persona |
| Routed QA | LLM/deterministic node | Run profile-specific validation |
| Supervisor | Deterministic node | Decide: loop, finish, or fail |
| Integrator | Deterministic node | Generated-code mode creates a local commit; Project Mode previews/applies selected-folder files without commit/push |
| LLMPool | Service | Route requests to healthy nodes by capability |
| RAG Retriever | Service | Provide relevant standards/examples as context |
| MCP Manager | Service | Expose filesystem, git, and shell tools |

The Supervisor and Integrator are deterministic — they make no LLM judgment calls — which removes a class of failure modes (see `architecture-edge-cases.md`, EC-17).

## Workflow Graph (Revised with Resilience)

Project Mode chat first passes through the Project Chat Router. The router
uses the local model as the primary semantic classifier, while a narrow
deterministic guard handles empty messages and safety normalization. The
resulting intent is converted into a concrete Project Action
Decision. A small action registry owns action-specific validation and
execution. Read-only actions such as `path_info`, `list_folder`, `read_file`,
`current_time`, `calculate`, and `assistant_capabilities` are executed directly.
Project-file actions are validated against the selected project root, while
clock/math/capability answers come from deterministic handlers instead of model
memory. Only `analyze_project` and `modify_project`
enter the LangGraph workflow below.

```
PROJECT MODE CHAT
      │
      ▼
┌──────────────────────┐
│ PROJECT CHAT ROUTER  │  model-first intent + policy normalization
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ PROJECT ACTION       │  direct_chat, project_status,
│ ROUTER + POLICY      │  path_info, list_folder,
│                      │  read_file, current_time,
│                      │  calculate, capabilities,
│                      │  analyze_project, modify_project
└──────────┬───────────┘
           │
   ┌───────┴──────────────────────────────────────┐
   ▼                                              ▼
direct/status/path_info/list/read/time/calc/capabilities   analyze_project/modify_project
   │                                              │
   ▼                                              ▼
┌──────────────────────┐                         LangGraph workflow
│ DIRECT RESPONDER OR  │                         below
│ READ-ONLY EXECUTOR   │
└──────────┬───────────┘
           ▼
          END

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
                      │INTEGRATOR│  generated-code commit,
                      │          │  Project Mode preview/apply
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

`LLMPool` routes by capability (CHAT, CODER, REASONER, VISION, FALLBACK), not
by round-robin. Each node has a health state and a circuit breaker. If a
configured specialized text node is unavailable and a fallback node is usable,
requests route to fallback. VISION never falls back to a text-only model and is
not part of core degraded-mode checks. The UI records and displays degraded mode
when the current pool cannot serve every required text capability. (EC-01,
EC-02, EC-03)

### Project Chat Intent Routing

The Project Mode UI does not treat every message as a code task. The Project
Chat Router runs before LangGraph and returns structured intents:
`conversation`, `file_inspection`, `folder_listing`, `path_info`, `help`, `status`,
`project_analysis`, `implementation`, or `clarify`. Natural-language intent
classification is model-first: casual
Turkish/English, typos, and project-analysis phrasing are interpreted by the
local CHAT model through structured output rather than by a large phrase
table. A deterministic policy layer still handles non-semantic safety rules:
empty messages, invalid workflow flags, model failures, and confidence below
the product threshold.

After intent routing, the model-selected action schema is dispatched through a
Project Action Registry. The code does not maintain a growing natural-language
phrase table for semantic intent detection; it validates and executes actions
selected by the router. Examples: `conversation -> direct_chat`,
`folder_listing -> list_folder`, `file_inspection -> read_file`, `path_info ->
path_info`, clock/date questions -> `current_time`, `project_analysis ->
analyze_project`, capability questions -> `assistant_capabilities`, simple
arithmetic -> `calculate`, and `implementation -> modify_project`.
Registered read-only handlers are checked against the selected project root,
readable file extensions, and size limits before execution. Direct routes are saved as
project timeline messages when the registry is available and never enter
Project Intake, Developer, Reviewer, QA, file writes, commits, or pushes. The
LLM direct responder receives a reduced history block so casual chat cannot
treat the previous task as the current request. Its response is also grounded
by source: without an action or workflow result, claims that it read, wrote,
tested, committed, pushed, or otherwise changed project files are rejected and
replaced by a safe fallback. The UI exposes both the final route and action
metadata, for example
`model: project_analysis, confidence: 0.84` and `action: analyze_project`.
It also records `responseSource` so the UI can distinguish an action executor,
LLM responder, vision response, fallback, or full workflow response. If a user
attaches a PNG/JPEG/WebP image, the API validates size/type and asks VISION for
a bounded screenshot/image summary. Direct image questions return that summary
without Project Intake or Developer/QA. If the same message is explicitly routed
as `implementation -> modify_project`, the vision summary is copied into
`project_vision_context` and becomes read-only workflow context; the attachment
alone never starts code changes. The React project sidebar filters stale
missing-path records and deduplicates projects by normalized path before
rendering.

### Warm-Up Phase

Before the workflow starts, a warm-up step sends a trivial prompt to each configured LLM node so models are resident in memory when possible. RAG and embedding failures are handled by the retriever's graceful-degradation path rather than by a blocking startup check. (EC-04, EC-26, EC-27)

### Structured Output with Fail-Safe Fallback

Agents that must return structured data use `with_structured_output()`. The
Developer node validates the returned files. If the output is empty,
unsupported, or syntactically invalid, the second attempt is a validation-aware
repair pass: the Developer receives the rejected code plus the deterministic
validation error as BLOCKER feedback. If the repair output is still unusable,
the workflow fails honestly and keeps the rejected code in technical state for
debugging instead of writing it. Reviewer structured-output failures are caught
by the node error boundary, producing a FAILED workflow rather than an
accidental approval. (EC-08, EC-10)

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
recent timeline events, and compacted memory chunks.

Project memory has two layers. Postgres is the durable source of truth through
`project_memory_chunks`, which stores bounded summaries of non-ephemeral
project exchanges with kind, importance, source metadata, and a dedupe key.
ChromaDB holds a secondary `project_memory` collection used only for semantic
retrieval; if embeddings or Chroma are unavailable, the system keeps running
with recent/checkpoint memory. New project messages retrieve only memories
scoped to the selected `project_path`, cap the prompt section, and append it as
`Relevant semantic project memory`. Ephemeral answers such as current time or
simple arithmetic are deliberately not compacted into long-term memory.

On a successful Project Mode run, the Integrator is preview-only by default:
it records `integration_planned_files`, `integration_file_actions`, and a
unified `integration_diff`. Streamlit stores the pending apply payload in
session state. The React API stores generated file content in a short-lived
server-side pending-apply registry and returns only a token plus planned files,
file actions, and diff metadata to the browser. The React UI writes generated
files only after the user clicks the apply button and calls
`POST /api/project-apply`; typing "Değişiklikleri uygula" into chat is treated
as a normal message, not as an implicit write. The write step uses the same MCP
path boundary and records `integration_written_files`. The Project Registry
then marks the matching checkpoint as applied and appends a `project_apply`
timeline event. It does not auto-commit or push the target project; those
actions remain human-gated. The generated-code mode continues to write into
isolated `workspace/task-{id}/` folders and create local commits there.

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

Project Chat route metadata is part of profile selection. When the model router
admits a message as `implementation` with action `modify_project`, that signal
is carried into `AgentState` before the workflow starts. This keeps terse or
typo-heavy artifact requests such as "python class/sınıf olsun" in the Python
profile instead of falling back to advisory `PROJECT_PROPOSAL.md` output.

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
  mode              "generate"|"project" in the UI; "review" is retained in the state type as an extension point
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
  project_chat_intent str          Project Chat router intent for workflow runs
  project_chat_action str          concrete action, e.g. modify_project
  project_chat_route_source str    policy, model, or fallback
  project_chat_confidence float    router confidence for the workflow admission
  project_vision_context str       optional VISION summary for attached images
  plan              list[str]      from Analyst
  code              dict[str,str]  filename -> content, from Developer
  dev_repair_attempted bool        true when validation-aware repair ran
  dev_validation_error str         Developer output validation detail
  dev_rejected_code dict[str,str]  invalid code retained for technical debug
  rag_context       list[str]      retrieved chunks
  rag_status        str            retrieved, empty, disabled, or unavailable
  rag_message       str            user-facing RAG status detail
  rag_chunk_count   int            retrieved chunk count
  review_feedback   list[Feedback] from Reviewer
  test_results      TestResults    from QA
  integration_message str          Integrator result or preview/apply message
  integration_branch  str          local branch used by generated-code commits
  integration_committed bool       true when generated-code mode created a local commit
  integration_target_path str      Project Mode folder previewed/written by Integrator
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
        │ nodes for requested│
        │ capability         │
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

The current UI runs one workflow task at a time through the sequential graph.
In Project Mode, direct conversation, help, status, path-info, folder-listing,
file-inspection, and clarify messages are handled before this graph by
Project Chat Router -> Project Action Router/Policy -> Project Chat Responder:

```
Project Intake -> Project Brief -> Task Classifier -> RAG -> Analyst -> Developer -> Reviewer -> QA -> Supervisor -> Integrator
```

For normal generated-code runs, Project Intake and Project Brief are no-ops. In
Project Mode, only workflow-routed messages collect context from the selected
`project_path` before RAG and planning, and the Integrator previews generated
file writes as a unified diff. Generated task mode remains isolated under
`workspace/task-{id}/`;
successful or warning-completed tasks are committed in that directory on
`feat/task-{id}`. If that branch already exists in the generated task
repository, the MCP git tool appends a numeric suffix such as
`feat/task-{id}-2`. A future batch runner can use LangGraph
`abatch(..., return_exceptions=True)` over the same compiled workflow, but
`app/graph/pipeline.py` and a multi-task UI are not part of the current
implementation.

## Git and Remote Push

Agents do not push to a remote. In generated-code mode, the deterministic
Integrator writes final code through the workspace MCP server and asks that
server to create a local git commit. In Project Mode, the Integrator is
preview-only by default and writes to the selected project folder only after
the user clicks the apply button; it does not create a commit or push.

After a SUCCESS or COMPLETED_WITH_WARNINGS generated-code result, the
Integrator creates `workspace/task-{id}/`, initializes a git repository there
if needed, checks out `feat/task-{id}` or an available suffixed branch, writes
a `.gitignore` for generated test artefacts, and commits the generated code
and tests with a deterministic `feat:` subject derived from the task. The
Integrator writes `integration_message`, `integration_branch`, and
`integration_committed` back into workflow state for the UI. FAILED tasks
never reach the Integrator.

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
running tests or creating the final generated-code commit. In Project Mode,
the Integrator first produces a diff preview for the selected folder and only
writes files after explicit apply. The QA agent returns test code; the QA node
runs it through the MCP pytest tool.

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
