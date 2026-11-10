"""
Retriever: Supports Dense Vector Search, BM25 Lexical Search, and Hybrid RRF Fusion.

Fulfills assignment capability B:
- Explicit method for prioritizing relevant evidence
- Comparative ranking across two retrieval paradigms (Dense Cosine vs BM25 Keyword)
- Hybrid Reciprocal Rank Fusion (RRF) for optimal precision and recall.
"""

import logging
from typing import Literal

from .bm25 import get_bm25_index
from .config import DEFAULT_TOP_K
from .ingest import get_collection, get_embedding_model
from .models import ChunkResult

logger = logging.getLogger(__name__)


def search_dense(query: str, top_k: int = DEFAULT_TOP_K) -> list[ChunkResult]:
    """Dense semantic retrieval via sentence-transformers embeddings in ChromaDB."""
    model = get_embedding_model()
    collection = get_collection()

    if collection.count() == 0:
        return []

    query_embedding = model.encode([query], show_progress_bar=False).tolist()

    results = collection.query(
        query_embeddings=query_embedding,
        n_results=min(top_k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    chunks: list[ChunkResult] = []
    if not results["documents"] or not results["documents"][0]:
        return chunks

    for doc, metadata, distance in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        similarity = round(1.0 - (distance / 2.0), 4)
        chunks.append(
            ChunkResult(
                text=doc,
                source=metadata.get("source", "unknown"),
                score=similarity,
                format=metadata.get("format", "markdown"),
            )
        )

    return chunks


def search_bm25(query: str, top_k: int = DEFAULT_TOP_K) -> list[ChunkResult]:
    """Lexical/sparse keyword retrieval using Okapi BM25."""
    bm25 = get_bm25_index()
    raw_results = bm25.search(query, top_k=top_k)

    chunks: list[ChunkResult] = []
    for item in raw_results:
        meta = item["metadata"]
        chunks.append(
            ChunkResult(
                text=item["text"],
                source=meta.get("source", "unknown"),
                score=item["score"],
                format=meta.get("format", "markdown"),
            )
        )
    return chunks


def search_hybrid(query: str, top_k: int = DEFAULT_TOP_K, rrf_k: int = 60) -> list[ChunkResult]:
    """
    Hybrid Retrieval combining Dense Semantic Search and BM25 Lexical Search
    using Reciprocal Rank Fusion (RRF).

    Formula:
        RRF_Score(d) = (1 / (rrf_k + rank_dense(d))) + (1 / (rrf_k + rank_bm25(d)))
    """
    candidate_limit = max(top_k * 2, 10)
    dense_results = search_dense(query, top_k=candidate_limit)
    bm25_results = search_bm25(query, top_k=candidate_limit)

    # Key documents by (source + text_snippet)
    scores: dict[str, float] = {}
    doc_map: dict[str, ChunkResult] = {}

    for rank, chunk in enumerate(dense_results, start=1):
        key = f"{chunk.source}::{chunk.text[:80]}"
        scores[key] = scores.get(key, 0.0) + (1.0 / (rrf_k + rank))
        doc_map[key] = chunk

    for rank, chunk in enumerate(bm25_results, start=1):
        key = f"{chunk.source}::{chunk.text[:80]}"
        scores[key] = scores.get(key, 0.0) + (1.0 / (rrf_k + rank))
        if key not in doc_map:
            doc_map[key] = chunk

    sorted_keys = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)

    fused_results: list[ChunkResult] = []
    max_rrf = max(scores.values()) if scores else 1.0

    for key in sorted_keys[:top_k]:
        base_chunk = doc_map[key]
        normalized_score = round(min(1.0, scores[key] / max_rrf), 4)
        fused_results.append(
            ChunkResult(
                text=base_chunk.text,
                source=base_chunk.source,
                score=normalized_score,
                format=base_chunk.format,
            )
        )

    return fused_results


def search(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    method: Literal["dense", "bm25", "hybrid"] = "hybrid",
) -> list[ChunkResult]:
    """Unified search entry point selecting the requested retrieval method."""
    if method == "dense":
        return search_dense(query, top_k=top_k)
    elif method == "bm25":
        return search_bm25(query, top_k=top_k)
    else:
        return search_hybrid(query, top_k=top_k)


def get_collection_count() -> int:
    """Return the total number of chunks in the collection."""
    return get_collection().count()
