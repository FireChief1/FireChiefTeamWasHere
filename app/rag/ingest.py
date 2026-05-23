"""Ingest the docs/ knowledge base into ChromaDB for RAG retrieval.

Each markdown document is split into chunks (one per second-level section),
embedded with nomic-embed-text, and stored in ChromaDB.

Run from the project root:

    python -m app.rag.ingest
"""

from __future__ import annotations

from loguru import logger

from app.config import settings
from app.rag.store import get_collection, get_embeddings


def source_domain(source: str) -> str:
    """Return the top-level docs domain for a source path."""
    return source.split("/", 1)[0] if "/" in source else "general"


def chunk_markdown(text: str) -> list[str]:
    """Split markdown into chunks, one per second-level (`## `) section.

    The engineering docs are written with self-contained `## ` sections, so
    each section makes a coherent, retrievable chunk.

    Args:
        text: The full markdown document.

    Returns:
        The list of non-empty chunks.
    """
    chunks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("## ") and current:
            chunks.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        chunks.append("\n".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def ingest() -> int:
    """Ingest every markdown file under docs/ into ChromaDB.

    Returns:
        The number of chunks ingested.
    """
    collection = get_collection(create=True)
    docs = sorted(settings.docs_dir.rglob("*.md"))

    documents: list[str] = []
    ids: list[str] = []
    metadatas: list[dict[str, str]] = []
    for doc in docs:
        source = str(doc.relative_to(settings.docs_dir))
        for index, chunk in enumerate(chunk_markdown(doc.read_text())):
            documents.append(chunk)
            ids.append(f"{source}::{index}")
            metadatas.append({"source": source, "domain": source_domain(source)})

    if not documents:
        logger.warning("no markdown documents found under docs/")
        return 0

    logger.info(f"embedding {len(documents)} chunks from {len(docs)} files...")
    vectors = get_embeddings().embed_documents(documents)
    collection.add(
        ids=ids, documents=documents, embeddings=vectors, metadatas=metadatas
    )
    logger.info(f"ingested {len(documents)} chunks into ChromaDB")
    return len(documents)


if __name__ == "__main__":
    count = ingest()
    print(f"Ingested {count} chunks into ChromaDB.")
