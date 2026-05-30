"""ChromaDB-backed storage for the RAG knowledge base.

Embeddings are computed with the local nomic-embed-text model via Ollama;
ChromaDB is used purely as the vector store.
"""

from __future__ import annotations

import contextlib
from typing import Any

import chromadb
from langchain_ollama import OllamaEmbeddings

from app.config import settings

COLLECTION_NAME = "knowledge"
PROJECT_MEMORY_COLLECTION_NAME = "project_memory"

# Bumped whenever the indexing recipe changes (distance space, embedding
# prefixes). Retrieval reads it from collection metadata so an index built by an
# older ingest keeps working with legacy retrieval until it is re-ingested.
RAG_INDEX_VERSION = "2"
# nomic-embed-text is trained with asymmetric task prefixes; using them
# materially improves retrieval relevance.
DOC_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "


def get_collection(*, create: bool = False) -> Any:
    """Return the RAG ChromaDB collection.

    Args:
        create: If True, drop and recreate the collection. Used by ingestion
            so each ingest starts from a clean state.

    Returns:
        The ChromaDB collection object.
    """
    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    if create:
        # The collection may not exist yet on a first ingest.
        with contextlib.suppress(Exception):
            client.delete_collection(COLLECTION_NAME)
        return client.create_collection(
            COLLECTION_NAME,
            metadata={
                "hnsw:space": "cosine",
                "embedding_model": settings.embedding_model,
                "index_version": RAG_INDEX_VERSION,
            },
        )
    return client.get_or_create_collection(COLLECTION_NAME)


def get_project_memory_collection(*, create: bool = False) -> Any:
    """Return the ChromaDB collection used for semantic project memory."""
    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    if create:
        with contextlib.suppress(Exception):
            client.delete_collection(PROJECT_MEMORY_COLLECTION_NAME)
        return client.create_collection(PROJECT_MEMORY_COLLECTION_NAME)
    return client.get_or_create_collection(PROJECT_MEMORY_COLLECTION_NAME)


def get_embeddings() -> OllamaEmbeddings:
    """Return the Ollama embedding model used for the knowledge base."""
    return OllamaEmbeddings(
        model=settings.embedding_model,
        base_url=settings.ollama_base_url,
    )
