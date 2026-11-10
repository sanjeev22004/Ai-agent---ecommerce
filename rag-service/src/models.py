"""
Pydantic request/response models — the API contract.
The TypeScript policy_search tool sends SearchRequest and expects SearchResponse.
"""

from typing import Literal
from pydantic import BaseModel, Field


# ─── Search ───────────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    """Incoming search query from the MCP policy_search tool."""
    query: str = Field(..., description="Natural language question about policies", min_length=1)
    top_k: int = Field(default=3, description="Number of chunks to return", ge=1, le=10)
    method: Literal["dense", "bm25", "hybrid"] = Field(
        default="hybrid",
        description="Retrieval ranking method: 'dense' (ChromaDB), 'bm25' (lexical), or 'hybrid' (RRF fusion)"
    )


class ChunkResult(BaseModel):
    """A single retrieved chunk with metadata."""
    text: str = Field(..., description="The chunk text content")
    source: str = Field(..., description="Source document filename")
    score: float = Field(..., description="Similarity or fusion score (0-1, higher is better)")
    format: str = Field(default="markdown", description="Document format: markdown, json, or pdf")


class SearchResponse(BaseModel):
    """Response containing ranked chunks from the vector store."""
    query: str
    results: list[ChunkResult]
    total_chunks: int = Field(..., description="Total chunks in the collection")
    method: str = Field(default="hybrid", description="Retrieval method used")


# ─── Ingest ───────────────────────────────────────────────────────────────────

class IngestResponse(BaseModel):
    """Response after ingesting/re-ingesting policy documents."""
    documents_processed: int
    total_chunks: int
    formats_detected: list[str]
    message: str


# ─── Health ───────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    collection_name: str
    total_chunks: int
    embedding_model: str
    methods_supported: list[str] = ["dense", "bm25", "hybrid"]
