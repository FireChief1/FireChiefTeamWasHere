# Multi-Agent Code Development Team

A local multi-agent code development system that simulates a small software
team using open-source LLMs. Specialized agents collaborate to turn a project
chat message or task description into reviewed, tested output — with no paid
APIs and no data leaving the machine.

Built as a final project for the Data Science / AI / LLM bootcamp.

## How It Works

Agents collaborate under a LangGraph orchestrator:

| Agent | Role |
|-------|------|
| Project Chat Router | Uses the local model plus safety checks to decide chat vs workflow |
| Project Action Router | Registry-backed action layer for `path_info`, `read_file`, `list_folder`, `current_time`, `calculate`, `assistant_capabilities`, `analyze_project`, or `modify_project` |
| Project Chat Responder | Answers direct conversation/status/help messages without Developer/QA |
| Project Intake | Scans the selected project folder in Project Mode |
| Project Brief | Detects stack, entrypoints, test commands, and risks |
| Task Classifier | Selects the implementation profile for the task |
| Analyst | Breaks the task into a structured plan |
| Routed Developer | Uses the Python or Static Web developer persona |
| Routed Reviewer | Uses the Python or Static Web reviewer persona |
| Routed QA | Runs pytest for Python or deterministic static-web checks |

A deterministic Supervisor decides whether to loop back for fixes or finish.
The deterministic Integrator commits generated-code runs to a local branch,
while Project Mode uses preview/apply and does not commit or push the selected
project automatically.

The primary UI is being migrated to a security-first **React + TypeScript +
Vite** workspace backed by a small local Python JSON API. The older Streamlit
surface remains available during the migration, but new Project Mode UI work
lands in `frontend/` first.

The UI includes a **Project Mode** foundation. In that mode the workflow
accepts a target project folder, starts with Project Intake and Project Brief
steps that scan that folder's files, task-related text matches, git status,
bounded diff summary, stack signals, likely entrypoints, test commands, and
project-level risks, then passes that context to the Analyst, Developer, and
Reviewer.
Project selections are stored in a Postgres-backed Project Registry, so the
sidebar can show recent projects and reopen one with its latest brief,
checkpoint history, timeline events, and saved project memory. Project Mode
uses a chat-first main panel: the user sends a project message, the agent
workflow runs in the background, and the final assistant response is saved back
to the project timeline. Before the workflow starts, a Project Chat Intent
Router asks the local model for a structured intent and concrete action
decision. The registry-backed Project Action layer validates and executes that
action; it does not grow a phrase table for semantic intent detection. Casual
questions, status checks, and help messages are answered by a separate Project
Chat Responder without Project Intake, RAG, Developer, Reviewer, or QA. The UI shows compact routing
metadata such as `model: project_analysis, confidence: 0.84`, plus action
metadata such as `path_info`, `read_file`, or `analyze_project`, plus the
response source (`action`, `model`, `vision`, `fallback`, or `workflow`). Read-only
actions are handled by registered action handlers and validated against the selected
project root before execution. Path requests return paths without reading file
contents, clock/math/capability questions use deterministic read-only actions
instead of model memory, and the current project stack is not treated as the
assistant's full ability boundary. The React project sidebar hides stale missing-path records and
deduplicates by project path before rendering. Technical Project/Developer/QA events remain
available in a collapsed details panel. The sidebar can rename or remove
registry entries without touching files on disk. Registry reads use a short
Streamlit cache so routine rerenders do not repeatedly hit Postgres.
Direct chat responses are grounded by source: if the LLM responder claims it
read, wrote, tested, committed, or otherwise acted on files without an `action`
or `workflow` result, the response is discarded and replaced with a safe
fallback. This keeps previous task history from leaking into casual chat as if
new work had just been performed.
Project memory now has a compact semantic layer: each non-ephemeral project
exchange is compressed into a bounded Postgres `project_memory_chunks` row, then
optionally indexed into a ChromaDB `project_memory` collection. New project
messages retrieve only project-scoped relevant memory snippets and inject that
bounded section into router/responder/workflow context. Raw timeline remains
available for UI history, but the model does not receive an ever-growing chat
transcript.
Project Chat can also accept one optional image attachment (PNG, JPEG, or WebP,
up to 5 MB). Images use the lazy VISION capability (`qwen2.5vl:7b` by default)
only when a picture is attached, so the core chat/coder workflow is not slowed
down at startup. Image-only or screenshot explanation requests return a direct
vision response. If the user explicitly asks to fix code based on the image,
the vision summary is passed into the normal workflow as context; the image
itself never auto-starts Developer/QA.
Successful Project Mode runs default to a preview-only Integrator step that
shows a unified diff and the files that would be written. Generated files are
applied only when the user clicks the Project Mode apply button, and that apply
event updates the project checkpoint/timeline. The React UI receives a
server-side apply token, shows planned files, file actions, and the unified
diff, then calls the local apply endpoint without exposing generated file
contents as a reusable API payload. Automatic git commits are still limited to
isolated generated-code runs; direct project commit/push remains human-gated.

Project Mode is profile-aware. A simple HTML/CSS task is routed to the
`static_web` profile, which produces files like `index.html` and validates them
as static web artifacts instead of forcing Python filenames and pytest. The UI
also renders generated HTML in a browser-like preview. The `project` profile is
kept conservative: project-analysis or recommendation tasks produce a grounded
`PROJECT_PROPOSAL.md` instead of rewriting source/artifact files. Relevant file
excerpts from the selected folder are included in the prompt so proposals and
static-web edits preserve the existing project subject matter unless the user
explicitly asks to replace it. Documentation tasks use the `docs` profile and
produce Markdown/text files such as `README.md` or `docs/architecture.md`.
When Project Chat admits a request as `implementation`/`modify_project`, that
router decision is carried into the workflow so terse Python artifact requests
such as "python class/sınıf olsun" use the Python profile rather than the
advisory project profile.

Developer output is validated before any write. If generated files are empty,
unsupported, or syntactically invalid, the retry is a repair pass that includes
the rejected code and validation error as feedback. If repair still fails, the
workflow stops without writing files and the React technical panel can show the
validation error plus rejected code for debugging.

## Technology Stack

- **LangGraph** — multi-agent orchestration (state machine, conditional edges)
- **LangChain** — agent prompts, structured output, LLM calls
- **MCP** — tool integration (filesystem, project search, shell, git)
- **RAG (ChromaDB)** — retrieves coding standards as context for agents
- **Ollama** — runs local Qwen2.5 models
- **React + TypeScript + Vite** — project chat workspace UI
- **Postgres** — project registry, timeline, checkpoints, run history

All components are free and open-source (MIT / Apache 2.0).

## Deployment

- **Core:** a single machine running local Qwen2.5 models. Project Chat uses
  `qwen2.5:14b` through the CHAT capability, while code workflow agents use
  `qwen2.5-coder:14b` through the CODER and REASONER capabilities. FALLBACK
  defaults to the general `qwen2.5:14b` node so it stays independent of the
  coder node — an open coder circuit can still fall back instead of failing.
- **Optional vision:** `qwen2.5vl:7b` serves VISION lazily for image/screenshot
  interpretation. Missing vision does not mark the core pool degraded.
- **Current workflow:** one task at a time through a sequential LangGraph state
  machine: Project Intake -> Project Brief -> Task Classifier -> RAG ->
  Analyst -> Developer -> Reviewer -> QA -> Supervisor -> Integrator. Project
  Intake and Project Brief are active only in Project Mode.
- **Optional future scale-out:** additional LLM nodes can be registered in the
  pool factory; batch/pipeline execution is an extension point, not part of the
  current UI workflow.

## Setup

```bash
# 1. Install Ollama and pull models
brew install ollama
ollama serve            # in a separate terminal
ollama pull qwen2.5:14b
ollama pull qwen2.5-coder:14b
ollama pull qwen2.5vl:7b   # optional, enables image/screenshot analysis
ollama pull nomic-embed-text

# 2. Install Python dependencies
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 3. Configure environment
cp .env.example .env

# 4. Start the Postgres database (stores run history)
docker compose up -d

# 5. Ingest the knowledge base into RAG
# (re-run after upgrading: the index now uses cosine distance + nomic-embed
#  search prefixes, and records its embedding model for mismatch detection)
python -m app.rag.ingest

# 6. Run the local API for the React UI
python -m app.api.server

# 7. Install and run the React UI
npm --prefix frontend ci --ignore-scripts
npm --prefix frontend run dev

# Legacy Streamlit UI remains available during migration
streamlit run app/ui/streamlit_app.py
```

Open the React workspace at `http://127.0.0.1:5173`. The local API listens on
`http://127.0.0.1:8765`.

Frontend dependencies are intentionally minimal and exact-pinned. Lifecycle
install scripts are disabled in `frontend/.npmrc`; use `npm ci --ignore-scripts`
instead of ad-hoc installs.

## Project Structure

```
app/
├── config.py        # central settings
├── api/             # local JSON API for the React UI
├── llm/             # capability-aware LLM pool
├── agents/          # Analyst, Developer, Reviewer, QA
├── graph/           # LangGraph workflow, supervisor, integrator
├── rag/             # ChromaDB ingestion and retrieval
├── tools/           # MCP tool integration
├── history.py       # Postgres-backed run history
└── ui/              # Streamlit interface
frontend/            # React + TypeScript + Vite project workspace UI
docs/                # engineering standards + architecture (RAG knowledge base)
tests/               # test suite
```

## Documentation

- `docs/architecture.md` — system architecture
- `docs/architecture-edge-cases.md` — failure-mode register
- `docs/frontend/supply-chain-security.md` — frontend dependency policy
- `docs/` — coding standards, testing, security, patterns
