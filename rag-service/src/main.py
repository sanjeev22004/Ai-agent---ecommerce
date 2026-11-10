"""
FastAPI app — the RAG microservice entry point.

Endpoints:
  POST /search  — query policy documents (Dense, BM25, or Hybrid)
  POST /ingest  — re-ingest policy documents from disk across multiple formats
  GET  /health  — health check with collection stats and supported methods
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from .config import CHROMA_COLLECTION, EMBEDDING_MODEL, HOST, PORT
from .ingest import ingest_documents, get_collection
from .models import (
    HealthResponse,
    IngestResponse,
    SearchRequest,
    SearchResponse,
)
from .retriever import get_collection_count, search

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ─── Lifespan: auto-ingest on startup ────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ingest policy documents when the service starts."""
    logger.info("Starting RAG service — auto-ingesting policy & FAQ documents...")
    try:
        docs_count, chunks_count, formats = ingest_documents()
        logger.info(f"Ingested {docs_count} documents ({', '.join(formats)}) → {chunks_count} chunks")
    except Exception as e:
        logger.error(f"Startup ingestion warning: {e}")
    yield
    logger.info("RAG service shutting down")


app = FastAPI(
    title="E-Commerce Policy RAG Service",
    description="Multi-format Retrieval-Augmented Generation service supporting Dense, BM25, and Hybrid RRF ranking",
    version="2.0.0",
    lifespan=lifespan,
)


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.post("/search", response_model=SearchResponse)
async def search_policies(request: SearchRequest) -> SearchResponse:
    """
    Search policy documents using the specified ranking approach.
    Default method is 'hybrid' (combining Dense Cosine and Okapi BM25 via RRF).
    """
    try:
        results = search(
            query=request.query,
            top_k=request.top_k,
            method=request.method,
        )
        return SearchResponse(
            query=request.query,
            results=results,
            total_chunks=get_collection_count(),
            method=request.method,
        )
    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@app.post("/ingest", response_model=IngestResponse)
async def ingest_policies() -> IngestResponse:
    """
    Re-ingest policy documents from disk across all supported formats (.md, .json).
    Re-indexes both ChromaDB vector embeddings and BM25 inverted index.
    """
    try:
        docs_count, chunks_count, formats = ingest_documents()
        return IngestResponse(
            documents_processed=docs_count,
            total_chunks=chunks_count,
            formats_detected=formats,
            message=f"Successfully ingested {docs_count} documents ({', '.join(formats)}) into {chunks_count} dual-indexed chunks",
        )
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check with collection statistics and capabilities."""
    return HealthResponse(
        status="healthy",
        collection_name=CHROMA_COLLECTION,
        total_chunks=get_collection_count(),
        embedding_model=EMBEDDING_MODEL,
        methods_supported=["dense", "bm25", "hybrid"],
    )
