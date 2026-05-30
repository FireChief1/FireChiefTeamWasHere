"""Central configuration for the multi-agent code development system.

Settings are loaded from environment variables (and an optional .env file).
This is the single source of truth for model names, timeouts, paths, and
workflow limits. Import `settings` from here; do not read os.environ directly.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime configuration, populated from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Ollama ---
    ollama_base_url: str = "http://localhost:11434"

    # --- Models ---
    chat_model: str = "qwen2.5:14b"
    coder_model: str = "qwen2.5-coder:14b"
    reasoner_model: str = "qwen2.5-coder:14b"
    # Fallback intentionally defaults to the general chat model rather than the
    # coder model. Sharing the coder tag would group fallback onto the same node
    # as CODER/REASONER, so an open coder circuit would leave no usable fallback.
    # Pointing it at the (already required) chat model gives a genuinely
    # independent node to fall back to at no extra model download.
    fallback_model: str = "qwen2.5:14b"
    vision_model: str = "qwen2.5vl:7b"
    embedding_model: str = "nomic-embed-text"

    # --- LLM pool behavior ---
    request_timeout: float = 180.0
    connect_timeout: float = 5.0
    max_retries: int = 3
    circuit_breaker_threshold: int = 3
    health_check_interval: int = 15
    # Context window passed to Ollama. Without this, Ollama uses its small
    # default (commonly 2048-4096 tokens) and silently truncates large
    # project-mode prompts (brief + file excerpts + RAG + memory + diff) from
    # the front, which can drop the system prompt or the task itself.
    llm_num_ctx: int = 8192
    # Upper bound on tokens generated per call. Bounds pathological repetition
    # loops and runaway output. Generous for this project's small modules; raise
    # for very large multi-file generation, or set to -1 to disable the cap.
    llm_num_predict: int = 4096
    # Fixed RNG seed passed to Ollama. A fixed integer makes generation
    # reproducible for the same prompt, which matters most for the temperature-0
    # router and the low-temperature reviewer. Set to -1 to let Ollama randomize.
    llm_seed: int = 0

    # --- Workflow limits ---
    max_iterations: int = 3
    test_timeout: int = 30

    # --- Project memory ---
    # Max active semantic memory chunks kept per project. New chunks evict the
    # lowest-importance, oldest ones (in Postgres and Chroma) so memory does not
    # grow without bound across a project's lifetime.
    project_memory_max_chunks: int = 200

    # --- RAG ---
    rag_top_k: int = 5
    chunk_size: int = 500
    chunk_overlap: int = 50
    # Max cosine distance (0=identical, 2=opposite) for a retrieved chunk to be
    # considered relevant. Chunks beyond this are dropped instead of injected as
    # noise. Applies only to cosine-space indexes (re-ingest to enable); set
    # higher to loosen, or to a large value to effectively disable filtering.
    rag_max_distance: float = 0.6

    # --- Paths (resolved relative to the project root) ---
    workspace_dir: Path = PROJECT_ROOT / "workspace"
    chroma_dir: Path = PROJECT_ROOT / "chroma_db"
    docs_dir: Path = PROJECT_ROOT / "docs"

    # --- Git (human-gated remote push) ---
    git_remote: str = ""
    git_token: str = ""

    # --- Database (Postgres, run via docker-compose) ---
    database_url: str = "postgresql://codeteam:codeteam@localhost:5434/codeteam"


settings = Settings()
