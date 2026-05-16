"""RAG retrieval over the docs/ knowledge base.

Retrieval degrades gracefully: if the knowledge base is empty or unavailable,
an empty result is returned so the workflow can proceed without RAG context.
"""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from app.config import settings
from app.rag.store import get_collection, get_embeddings


@dataclass
class RetrievedChunk:
    """A single chunk retrieved from the knowledge base.

    Attributes:
        text: The chunk text.
        source: The document the chunk came from.
    """

    text: str
    source: str


def retrieve(query: str, k: int | None = None) -> list[RetrievedChunk]:
    """Retrieve the knowledge chunks most relevant to a query.

    Args:
        query: The text to find relevant chunks for.
        k: The number of chunks to return. Defaults to the configured value.

    Returns:
        The retrieved chunks ordered by relevance, or an empty list if the
        knowledge base is empty or unavailable.
    """
    top_k = k if k is not None else settings.rag_top_k
    try:
        collection = get_collection()
        if collection.count() == 0:
            logger.warning("RAG knowledge base is empty -- run app.rag.ingest")
            return []
        query_vector = get_embeddings().embed_query(query)
        result = collection.query(
            query_embeddings=[query_vector], n_results=top_k
        )
    except Exception as exc:  # noqa: BLE001 - RAG is optional; degrade gracefully
        logger.warning(f"RAG retrieval unavailable: {exc}")
        return []

    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    return [
        RetrievedChunk(text=text, source=str((meta or {}).get("source", "?")))
        for text, meta in zip(documents, metadatas, strict=False)
    ]
