# Multi-Agent Code Development Team

A local multi-agent code development system that simulates a small software
team using open-source LLMs. Specialized agents collaborate to turn a task
description into reviewed, tested code — with no paid APIs and no data leaving
the machine.

Built as a final project for the Data Science / AI / LLM bootcamp.

## How It Works

Agents collaborate under a LangGraph orchestrator:

| Agent | Role |
|-------|------|
| Project Intake | Scans the selected project folder in Project Mode |
| Project Brief | Detects stack, entrypoints, test commands, and risks |
| Task Classifier | Selects the implementation profile for the task |
| Analyst | Breaks the task into a structured plan |
| Routed Developer | Uses the Python or Static Web developer persona |
| Routed Reviewer | Uses the Python or Static Web reviewer persona |
| Routed QA | Runs pytest for Python or deterministic static-web checks |

A deterministic Supervisor decides whether to loop back for fixes or finish,
and a deterministic Integrator commits the result to a local git branch.

The UI also includes a **Project Mode** foundation. In that mode the workflow
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
to the project timeline. Technical Project/Developer/QA events remain available
in a collapsed details panel. The sidebar can rename or remove registry entries
without touching files on disk. Registry reads use a short Streamlit cache so
routine rerenders do not repeatedly hit Postgres.
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

All components are free and open-source (MIT / Apache 2.0).

## Deployment

- **Core:** a single machine running `qwen2.5-coder:14b`. One model serves
  four agent personas.
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

# 6. Run the UI
streamlit run app/ui/streamlit_app.py
```

## Project Structure

```
app/
├── config.py        # central settings
├── llm/             # capability-aware LLM pool
├── agents/          # Analyst, Developer, Reviewer, QA
├── graph/           # LangGraph workflow, supervisor, integrator
├── rag/             # ChromaDB ingestion and retrieval
├── tools/           # MCP tool integration
├── history.py       # Postgres-backed run history
└── ui/              # Streamlit interface
docs/                # engineering standards + architecture (RAG knowledge base)
tests/               # test suite
```

## Documentation

- `docs/architecture.md` — system architecture
- `docs/architecture-edge-cases.md` — failure-mode register
- `docs/` — coding standards, testing, security, patterns
