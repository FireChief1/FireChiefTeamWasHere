# Multi-Agent Code Development Team

A pipeline-parallel multi-agent system that simulates a software development
team using local, open-source LLMs. Specialized agents collaborate to turn a
task description into reviewed, tested code — with no paid APIs and no data
leaving the machine.

Built as a final project for the Data Science / AI / LLM bootcamp.

## How It Works

Four agents collaborate under a LangGraph orchestrator:

| Agent | Role |
|-------|------|
| Analyst | Breaks the task into a structured plan |
| Developer | Writes the code |
| Reviewer | Inspects quality, correctness, and security |
| QA | Generates and runs tests |

A deterministic Supervisor decides whether to loop back for fixes or finish,
and a deterministic Integrator commits the result to a local git branch.

## Technology Stack

- **LangGraph** — multi-agent orchestration (state machine, conditional edges)
- **LangChain** — agent prompts, structured output, LLM calls
- **MCP** — tool integration (filesystem, shell, git) for agents
- **RAG (ChromaDB)** — retrieves coding standards as context for agents
- **Ollama** — runs local Qwen2.5 models

All components are free and open-source (MIT / Apache 2.0).

## Deployment

- **Core:** a single machine running `qwen2.5-coder:14b`. One model serves
  four agent personas.
- **Optional scale-out:** add worker PCs as extra pool nodes for real
  pipeline-parallel speedup. This is configuration, not a code change.

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

# 4. Ingest the knowledge base into RAG
python -m app.rag.ingest

# 5. Run the UI
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
└── ui/              # Streamlit interface
docs/                # engineering standards + architecture (RAG knowledge base)
tests/               # test suite
```

## Documentation

- `docs/architecture.md` — system architecture
- `docs/architecture-edge-cases.md` — failure-mode register
- `docs/` — coding standards, testing, security, patterns
