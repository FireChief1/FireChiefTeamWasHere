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

    # --- Models (single-machine core: one model serves every capability) ---
    coder_model: str = "qwen2.5-coder:14b"
    reasoner_model: str = "qwen2.5-coder:14b"
    fallback_model: str = "qwen2.5-coder:14b"
    embedding_model: str = "nomic-embed-text"

    # --- LLM pool behavior ---
    request_timeout: float = 180.0
    connect_timeout: float = 5.0
    max_retries: int = 3
    circuit_breaker_threshold: int = 3
    health_check_interval: int = 15

    # --- Workflow limits ---
    max_iterations: int = 3
    test_timeout: int = 30

    # --- RAG ---
    rag_top_k: int = 5
    chunk_size: int = 500
    chunk_overlap: int = 50

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
