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
| Project Chat Router | Uses the local model plus policy checks to decide chat vs workflow |
| Project Action Router | Registry-backed action layer for `path_info`, `read_file`, `list_folder`, `analyze_project`, or `modify_project` |
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
Router asks the local model for a structured intent decision, then a
registry-backed Project Action layer maps that intent to concrete behavior and
blocks low-confidence or unsafe routes. Casual questions, status checks, and
help messages are answered by a separate Project Chat Responder without
Project Intake, RAG, Developer, Reviewer, or QA. The UI shows compact routing
metadata such as `model: project_analysis, confidence: 0.84`, plus action
metadata such as `path_info`, `read_file`, or `analyze_project`. Read-only
actions are handled by registered action handlers and validated against the selected
project root before execution. Path requests return paths without reading file
contents. Technical Project/Developer/QA events remain
available in a collapsed details panel. The sidebar can rename or remove
registry entries without touching files on disk. Registry reads use a short
Streamlit cache so routine rerenders do not repeatedly hit Postgres.
Successful Project Mode runs default to a preview-only Integrator step that
shows a unified diff and the files that would be written. Generated files are
applied only when the user clicks the Project Mode apply button, and that apply
event updates the project checkpoint/timeline. Automatic git commits are still
limited to isolated generated-code runs; direct project commit/push remains
human-gated.

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

- **Core:** a single machine running `qwen2.5-coder:14b`. One model serves
  multiple focused personas through CODER, REASONER, and FALLBACK capabilities.
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
ollama pull qwen2.5-coder:14b
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
