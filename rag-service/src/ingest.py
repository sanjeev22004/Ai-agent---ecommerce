"""
Ingest pipeline: load markdown & JSON documents → chunk → embed → store in ChromaDB & BM25 index.

Processes multiple document/data formats:
- Markdown (.md) documents: split into paragraph chunks with overlap
- Structured JSON (.json) documents: formatted into question/answer chunks with tags
- Retains source references, format lineage, and metadata.
"""

import json
import logging
from pathlib import Path
from typing import Any

import chromadb
from sentence_transformers import SentenceTransformer

from .bm25 import get_bm25_index
from .config import (
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    CHROMA_COLLECTION,
    CHROMA_PERSIST_DIR,
    EMBEDDING_MODEL,
    POLICIES_DIR,
)

logger = logging.getLogger(__name__)

# ─── Module-level singletons ─────────────────────────────────────────────────

_chroma_client: chromadb.ClientAPI | None = None
_embedding_model: SentenceTransformer | None = None


def get_chroma_client() -> chromadb.ClientAPI:
    """Get or create the ChromaDB client (in-memory or persistent)."""
    global _chroma_client
    if _chroma_client is None:
        if CHROMA_PERSIST_DIR:
            _chroma_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
            logger.info(f"ChromaDB persistent client at {CHROMA_PERSIST_DIR}")
        else:
            _chroma_client = chromadb.Client()
            logger.info("ChromaDB in-memory client")
    return _chroma_client


def get_embedding_model() -> SentenceTransformer:
    """Get or create the embedding model (downloads on first use)."""
    global _embedding_model
    if _embedding_model is None:
        logger.info(f"Loading embedding model: {EMBEDDING_MODEL}")
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL)
        logger.info("Embedding model loaded")
    return _embedding_model


def get_collection() -> chromadb.Collection:
    """Get the ChromaDB collection, creating it if needed."""
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )


# ─── Chunking ────────────────────────────────────────────────────────────────


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    Split text into overlapping chunks by character count.
    Splits on paragraph boundaries first, then merges.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks: list[str] = []
    current_chunk = ""

    for paragraph in paragraphs:
        if current_chunk and len(current_chunk) + len(paragraph) + 2 > chunk_size:
            chunks.append(current_chunk.strip())
            if overlap > 0 and len(current_chunk) > overlap:
                current_chunk = current_chunk[-overlap:] + "\n\n" + paragraph
            else:
                current_chunk = paragraph
        else:
            if current_chunk:
                current_chunk += "\n\n" + paragraph
            else:
                current_chunk = paragraph

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


# ─── Document Loaders (Multi-Format) ──────────────────────────────────────────


def load_documents(policies_dir: Path = POLICIES_DIR) -> list[dict[str, Any]]:
    """
    Load documents from the policies directory across multiple formats.
    Supports .md (Markdown), .json (Structured FAQs/Knowledge), and .pdf (if present).
    """
    records: list[dict[str, Any]] = []
    if not policies_dir.exists():
        logger.warning(f"Policies directory not found: {policies_dir}")
        return records

    # 1. Load Markdown documents
    for md_file in sorted(policies_dir.glob("*.md")):
        try:
            content = md_file.read_text(encoding="utf-8")
            records.append({
                "filename": md_file.name,
                "content": content,
                "format": "markdown",
                "chunks": chunk_text(content),
            })
            logger.info(f"Loaded Markdown document: {md_file.name} ({len(content)} chars)")
        except Exception as e:
            logger.error(f"Error reading {md_file.name}: {e}")

    # 2. Load JSON documents (Format 2: structured FAQ catalog)
    for json_file in sorted(policies_dir.glob("*.json")):
        try:
            raw_data = json.loads(json_file.read_text(encoding="utf-8"))
            json_chunks: list[str] = []
            if isinstance(raw_data, list):
                for item in raw_data:
                    q = item.get("question", "")
                    a = item.get("answer", "")
                    cat = item.get("category", "")
                    tags = ", ".join(item.get("tags", []))
                    chunk_repr = f"Q: {q}\nA: {a}\nCategory: {cat}\nKeywords: {tags}"
                    json_chunks.append(chunk_repr)
            else:
                json_chunks.append(json.dumps(raw_data, indent=2))

            records.append({
                "filename": json_file.name,
                "content": json_file.read_text(encoding="utf-8"),
                "format": "json",
                "chunks": json_chunks,
            })
            logger.info(f"Loaded JSON document: {json_file.name} ({len(json_chunks)} FAQ items)")
        except Exception as e:
            logger.error(f"Error reading JSON {json_file.name}: {e}")

    # 3. Load PDF documents (Optional Format 3)
    for pdf_file in sorted(policies_dir.glob("*.pdf")):
        try:
            pdf_text = ""
            try:
                import pypdf
                reader = pypdf.PdfReader(str(pdf_file))
                for page in reader.pages:
                    pdf_text += (page.extract_text() or "") + "\n\n"
            except ImportError:
                try:
                    import fitz
                    doc = fitz.open(str(pdf_file))
                    for page in doc:
                        pdf_text += page.get_text() + "\n\n"
                except ImportError:
                    logger.warning("PDF libraries not installed; skipping PDF text extraction.")

            if pdf_text.strip():
                records.append({
                    "filename": pdf_file.name,
                    "content": pdf_text,
                    "format": "pdf",
                    "chunks": chunk_text(pdf_text),
                })
                logger.info(f"Loaded PDF document: {pdf_file.name}")
        except Exception as e:
            logger.error(f"Error processing PDF {pdf_file.name}: {e}")

    return records


# ─── Ingestion Pipeline ───────────────────────────────────────────────────────


def ingest_documents(policies_dir: Path = POLICIES_DIR) -> tuple[int, int, list[str]]:
    """
    Full ingest pipeline:
    1. Read documents across multiple formats (.md, .json)
    2. Split into chunks with preserved metadata
    3. Generate embeddings & store in ChromaDB (Dense)
    4. Index tokens in BM25Index (Lexical)
    """
    model = get_embedding_model()
    client = get_chroma_client()

    # Recreate ChromaDB collection cleanly
    try:
        client.delete_collection(CHROMA_COLLECTION)
        logger.info(f"Cleared existing ChromaDB collection: {CHROMA_COLLECTION}")
    except Exception:
        pass

    collection = client.get_or_create_collection(
        name=CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )

    doc_records = load_documents(policies_dir)
    if not doc_records:
        logger.warning("No documents found to ingest")
        return 0, 0, []

    all_chunks: list[str] = []
    all_ids: list[str] = []
    all_metadatas: list[dict[str, str]] = []
    formats_detected = list({doc["format"] for doc in doc_records})

    for doc in doc_records:
        filename = doc["filename"]
        fmt = doc["format"]
        chunks = doc["chunks"]

        for i, chunk in enumerate(chunks):
            chunk_id = f"{filename}::chunk_{i}"
            all_chunks.append(chunk)
            all_ids.append(chunk_id)
            all_metadatas.append({
                "source": filename,
                "format": fmt,
                "chunk_index": str(i),
            })

    # 1. Dense Indexing (SentenceTransformer + ChromaDB)
    logger.info(f"Computing embeddings for {len(all_chunks)} chunks...")
    embeddings = model.encode(all_chunks, show_progress_bar=False).tolist()

    collection.add(
        ids=all_ids,
        documents=all_chunks,
        embeddings=embeddings,
        metadatas=all_metadatas,
    )

    # 2. Lexical Indexing (Okapi BM25)
    logger.info(f"Fitting BM25 index on {len(all_chunks)} chunks...")
    bm25_index = get_bm25_index()
    bm25_index.fit(
        doc_ids=all_ids,
        documents=all_chunks,
        metadatas=all_metadatas,
    )

    logger.info(
        f"Ingestion complete: {len(doc_records)} documents ({', '.join(formats_detected)}) "
        f"→ {len(all_chunks)} chunks indexed in both ChromaDB and BM25"
    )

    return len(doc_records), len(all_chunks), formats_detected
