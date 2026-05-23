"""RAG retrieval over the docs/ knowledge base.

Retrieval degrades gracefully: if the knowledge base is empty or unavailable,
an empty result is returned so the workflow can proceed without RAG context.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from loguru import logger

from app.config import settings
from app.rag.store import get_collection, get_embeddings

_PROFILE_SOURCE_PREFIXES = {
    "python": (
        "coding-standards/",
        "testing/",
        "patterns/",
        "security/",
        "code-review/",
    ),
    "static_web": (
        "frontend/",
        "security/",
        "project-mode/",
        "code-review/",
    ),
    "docs": (
        "docs",
        "project-mode/",
        "git/",
    ),
    "project": (
        "project-mode/",
        "architecture",
        "patterns/",
        "git/",
        "code-review/",
    ),
}


@dataclass
class RetrievedChunk:
    """A single chunk retrieved from the knowledge base.

    Attributes:
        text: The chunk text.
        source: The document the chunk came from.
    """

    text: str
    source: str


@dataclass
class RetrievalResult:
    """RAG retrieval result with user-facing status metadata."""

    chunks: list[RetrievedChunk]
    status: Literal["retrieved", "empty", "unavailable"]
    message: str


def retrieve(
    query: str, k: int | None = None, profile: str | None = None
) -> list[RetrievedChunk]:
    """Retrieve the knowledge chunks most relevant to a query.

    Args:
        query: The text to find relevant chunks for.
        k: The number of chunks to return. Defaults to the configured value.

    Returns:
        The retrieved chunks ordered by relevance, or an empty list if the
        knowledge base is empty or unavailable.
    """
    return retrieve_with_status(query, k, profile=profile).chunks


def retrieve_with_status(
    query: str, k: int | None = None, profile: str | None = None
) -> RetrievalResult:
    """Retrieve relevant chunks and include RAG status metadata."""
    top_k = k if k is not None else settings.rag_top_k
    query_k = top_k if profile is None else max(top_k * 4, top_k)
    try:
        collection = get_collection()
        if collection.count() == 0:
            logger.warning("RAG knowledge base is empty -- run app.rag.ingest")
            return RetrievalResult(
                chunks=[],
                status="empty",
                message=(
                    "RAG knowledge base is empty. Run "
                    "`python -m app.rag.ingest` to ingest docs."
                ),
            )
        query_vector = get_embeddings().embed_query(query)
        result = collection.query(
            query_embeddings=[query_vector], n_results=query_k
        )
    except Exception as exc:  # noqa: BLE001 - RAG is optional; degrade gracefully
        logger.warning(f"RAG retrieval unavailable: {exc}")
        return RetrievalResult(
            chunks=[],
            status="unavailable",
            message=f"RAG retrieval unavailable: {exc}",
        )

    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    all_chunks = [
        RetrievedChunk(text=text, source=str((meta or {}).get("source", "?")))
        for text, meta in zip(documents, metadatas, strict=False)
    ]
    chunks = _profile_filtered_chunks(all_chunks, profile, top_k)
    if not chunks:
        return RetrievalResult(
            chunks=[],
            status="empty",
            message="RAG returned no matching context for this task.",
        )
    return RetrievalResult(
        chunks=chunks,
        status="retrieved",
        message=_retrieval_message(len(chunks), profile),
    )


def _profile_filtered_chunks(
    chunks: list[RetrievedChunk], profile: str | None, top_k: int
) -> list[RetrievedChunk]:
    """Prefer chunks from documentation domains that match the task profile."""
    if profile is None:
        return chunks[:top_k]
    matching = [
        chunk for chunk in chunks if _source_matches_profile(chunk.source, profile)
    ]
    return (matching or chunks)[:top_k]


def _source_matches_profile(source: str, profile: str) -> bool:
    """Return True when a source path belongs to the requested profile."""
    prefixes = _PROFILE_SOURCE_PREFIXES.get(profile)
    if not prefixes:
        return True
    return any(source.startswith(prefix) for prefix in prefixes)


def _retrieval_message(count: int, profile: str | None) -> str:
    """Build the human-readable RAG retrieval message."""
    if profile is None:
        return f"Retrieved {count} RAG chunk(s)."
    return f"Retrieved {count} RAG chunk(s) for profile `{profile}`."
