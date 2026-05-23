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


def split_large_chunk(text: str, max_chars: int, overlap: int) -> list[str]:
    """Split an oversized markdown chunk into embedding-safe pieces."""
    text = text.strip()
    if not text:
        return []
    if max_chars <= 0 or len(text) <= max_chars:
        return [text]

    safe_overlap = max(0, min(overlap, max_chars // 4))
    parts: list[str] = []
    current = ""
    for block in text.split("\n\n"):
        candidate = block if not current else f"{current}\n\n{block}"
        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            parts.append(current.strip())
            current = ""

        if len(block) <= max_chars:
            current = block
            continue

        parts.extend(_split_text_block(block, max_chars, safe_overlap))

    if current:
        parts.append(current.strip())
    return [part for part in parts if part]


def _split_text_block(text: str, max_chars: int, overlap: int) -> list[str]:
    """Split a single long paragraph or code block without infinite overlap."""
    parts: list[str] = []
    start = 0
    text = text.strip()
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            newline = text.rfind("\n", start, end)
            space = text.rfind(" ", start, end)
            boundary = max(newline, space)
            if boundary > start + (max_chars // 2):
                end = boundary

        part = text[start:end].strip()
        if part:
            parts.append(part)

        if end >= len(text):
            break
        next_start = max(end - overlap, start + 1)
        if next_start <= start:
            next_start = end
        start = next_start
    return parts


def ingest() -> int:
    """Ingest every markdown file under docs/ into ChromaDB.

    Returns:
        The number of chunks ingested.
    """
    docs = sorted(settings.docs_dir.rglob("*.md"))

    documents: list[str] = []
    ids: list[str] = []
    metadatas: list[dict[str, str]] = []
    for doc in docs:
        source = str(doc.relative_to(settings.docs_dir))
        for section_index, section in enumerate(chunk_markdown(doc.read_text())):
            chunks = split_large_chunk(
                section,
                max_chars=settings.chunk_size,
                overlap=settings.chunk_overlap,
            )
            for chunk_index, chunk in enumerate(chunks):
                documents.append(chunk)
                ids.append(f"{source}::{section_index}:{chunk_index}")
                metadatas.append(
                    {
                        "source": source,
                        "domain": source_domain(source),
                        "section_index": str(section_index),
                        "chunk_index": str(chunk_index),
                    }
                )

    if not documents:
        logger.warning("no markdown documents found under docs/")
        return 0

    logger.info(f"embedding {len(documents)} chunks from {len(docs)} files...")
    vectors = get_embeddings().embed_documents(documents)

    # Recreate the collection only after embeddings succeed. This keeps a
    # usable vector store intact when Ollama or the embedding model is down.
    collection = get_collection(create=True)
    collection.add(
        ids=ids, documents=documents, embeddings=vectors, metadatas=metadatas
    )
    logger.info(f"ingested {len(documents)} chunks into ChromaDB")
    return len(documents)


if __name__ == "__main__":
    count = ingest()
    print(f"Ingested {count} chunks into ChromaDB.")
