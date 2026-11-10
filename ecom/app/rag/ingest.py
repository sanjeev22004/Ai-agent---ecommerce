"""Policy ingestion and embedding pipeline for ecom.

Chunks markdown (.md), JSON (.json), and PDF (.pdf) documents from data/policies/
and embeds them into pgvector.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, List, Optional

from sentence_transformers import SentenceTransformer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.config import settings, POLICIES_DIR
from app.db.models import Policy

logger = logging.getLogger(__name__)

_embedding_model: Optional[SentenceTransformer] = None


def get_embedding_model() -> SentenceTransformer:
    """Get or initialize singleton SentenceTransformer model."""
    global _embedding_model
    if _embedding_model is None:
        logger.info("Loading embedding model '%s'...", settings.EMBEDDING_MODEL)
        try:
            _embedding_model = SentenceTransformer(settings.EMBEDDING_MODEL)
        except Exception as err:
            logger.warning("Normal load failed (%s), trying local_files_only=True...", err)
            _embedding_model = SentenceTransformer(settings.EMBEDDING_MODEL, local_files_only=True)
        logger.info("Embedding model loaded successfully.")
    return _embedding_model


def chunk_text(text: str, chunk_size: int = settings.CHUNK_SIZE, overlap: int = settings.CHUNK_OVERLAP) -> List[str]:
    """Split text into semantic paragraph-aware overlapping chunks."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: List[str] = []
    current_chunk = ""

    for para in paragraphs:
        if not current_chunk:
            current_chunk = para
        elif len(current_chunk) + len(para) + 2 <= chunk_size:
            current_chunk += "\n\n" + para
        else:
            chunks.append(current_chunk)
            if overlap > 0 and len(current_chunk) > overlap:
                overlap_text = current_chunk[-overlap:]
                current_chunk = overlap_text + "\n\n" + para
            else:
                current_chunk = para

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks if chunks else [text.strip()]


async def ingest_policies(session: AsyncSession, policies_dir: Optional[Path] = None) -> int:
    """Read all markdown, JSON, and PDF files in policies_dir, chunk, embed, and store in DB."""
    target_dir = policies_dir or POLICIES_DIR
    if not target_dir.exists():
        logger.warning("Policies directory %s does not exist. Skipping ingestion.", target_dir)
        return 0

    model = get_embedding_model()
    policy_records: List[Policy] = []
    base_effective_date = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    # 1. Process Markdown files (.md)
    for md_file in sorted(target_dir.glob("*.md")):
        logger.info("Ingesting markdown policy: %s", md_file.name)
        text = md_file.read_text(encoding="utf-8")
        title = md_file.stem.replace("_", " ").title()

        first_line = text.strip().split("\n")[0]
        if first_line.startswith("# "):
            title = first_line.lstrip("# ").strip()

        chunks = chunk_text(text)
        embeddings = model.encode(chunks, normalize_embeddings=True)

        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            chunk_title = f"{title} (Part {i + 1})" if len(chunks) > 1 else title
            record = Policy(
                title=chunk_title,
                content=chunk,
                format="markdown",
                source_file=md_file.name,
                version="1.0",
                effective_from=base_effective_date,
                effective_to=None,
                embedding=emb.tolist(),
            )
            policy_records.append(record)

    # 2. Process JSON FAQ files (.json)
    for json_file in sorted(target_dir.glob("*.json")):
        logger.info("Ingesting JSON knowledge: %s", json_file.name)
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                items_to_embed: List[str] = []
                temp_records: List[dict] = []

                for item in data:
                    q = item.get("question", "")
                    a = item.get("answer", "")
                    tags = ", ".join(item.get("tags", []))
                    content = f"Question: {q}\nAnswer: {a}\nRelated Tags: {tags}"
                    title = f"FAQ: {q}"

                    items_to_embed.append(content)
                    temp_records.append({
                        "title": title,
                        "content": content,
                        "format": "json",
                        "source_file": json_file.name,
                        "version": "1.0",
                    })

                if items_to_embed:
                    embeddings = model.encode(items_to_embed, normalize_embeddings=True)
                    for info, emb in zip(temp_records, embeddings):
                        record = Policy(
                            title=info["title"],
                            content=info["content"],
                            format=info["format"],
                            source_file=info["source_file"],
                            version=info["version"],
                            effective_from=base_effective_date,
                            effective_to=None,
                            embedding=emb.tolist(),
                        )
                        policy_records.append(record)
        except Exception as e:
            logger.error("Failed to parse JSON policy %s: %s", json_file.name, e)

    # 3. Process PDF files (.pdf)
    for pdf_file in sorted(target_dir.glob("*.pdf")):
        logger.info("Checking PDF policy: %s", pdf_file.name)
        pdf_text = ""
        try:
            import fitz
            doc = fitz.open(str(pdf_file))
            for page in doc:
                pdf_text += page.get_text() + "\n\n"
        except Exception:
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(pdf_file))
                for page in reader.pages:
                    pdf_text += (page.extract_text() or "") + "\n\n"
            except Exception as e:
                logger.error("Error reading PDF %s: %s", pdf_file.name, e)

        pdf_text = pdf_text.strip()
        if not pdf_text:
            logger.warning(
                "PDF '%s' contains no extractable digital text layer (scanned or image-only PDF). "
                "Text extraction returned 0 characters.",
                pdf_file.name,
            )
            continue

        title = pdf_file.stem.replace("_", " ").title()
        chunks = chunk_text(pdf_text)
        embeddings = model.encode(chunks, normalize_embeddings=True)

        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            chunk_title = f"{title} (Part {i + 1})" if len(chunks) > 1 else title
            record = Policy(
                title=chunk_title,
                content=chunk,
                format="pdf",
                source_file=pdf_file.name,
                version="1.0",
                effective_from=base_effective_date,
                effective_to=None,
                embedding=emb.tolist(),
            )
            policy_records.append(record)

    # Clean existing policies and insert fresh
    await session.execute(delete(Policy))
    session.add_all(policy_records)
    await session.commit()

    logger.info("Successfully ingested %d policy chunks into pgvector database.", len(policy_records))
    return len(policy_records)
