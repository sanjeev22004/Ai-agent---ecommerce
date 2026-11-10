"""Retriever for policy documents using pgvector cosine similarity search.

Supports active date filtering (effective_from <= order_date <= effective_to)
and both PostgreSQL + pgvector and in-process cosine similarity fallback modes.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Union

import numpy as np
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Policy
from app.rag.ingest import get_embedding_model

logger = logging.getLogger(__name__)


def parse_order_date(order_date_input: Union[str, datetime]) -> Optional[datetime]:
    """Parse various date formats into a timezone-aware UTC datetime."""
    if isinstance(order_date_input, datetime):
        if order_date_input.tzinfo is None:
            return order_date_input.replace(tzinfo=timezone.utc)
        return order_date_input

    if not isinstance(order_date_input, str) or not order_date_input.strip():
        return None

    raw = order_date_input.strip()
    formats = [
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(raw.replace("Z", ""), fmt.replace("Z", ""))
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    try:
        from dateutil import parser
        dt = parser.parse(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


async def search_policies(
    session: AsyncSession,
    query: str,
    top_k: int = 3,
    order_date: Optional[Union[str, datetime]] = None,
) -> List[Dict[str, Any]]:
    """Perform cosine similarity vector search over policies with optional date filtering."""
    if not query.strip():
        return []

    model = get_embedding_model()
    query_vector = model.encode(query, normalize_embeddings=True)
    query_list = query_vector.tolist()

    parsed_date = parse_order_date(order_date) if order_date else None

    # Base date filter conditions
    conditions = []
    if parsed_date:
        conditions.append(Policy.effective_from <= parsed_date)
        conditions.append(
            or_(
                Policy.effective_to.is_(None),
                Policy.effective_to >= parsed_date,
            )
        )

    # 1. Attempt PostgreSQL native pgvector cosine distance if on Postgres
    if settings.is_postgres:
        try:
            distance_col = Policy.embedding.cosine_distance(query_list)
            stmt = select(Policy, distance_col.label("distance"))
            if conditions:
                stmt = stmt.where(and_(*conditions))
            stmt = stmt.order_by(distance_col).limit(top_k)

            result = await session.execute(stmt)
            rows = result.all()

            results: List[Dict[str, Any]] = []
            for policy, distance in rows:
                sim = max(0.0, min(1.0, 1.0 - float(distance)))
                results.append({
                    "id": policy.id,
                    "title": policy.title,
                    "content": policy.content,
                    "format": policy.format,
                    "source_file": policy.source_file,
                    "version": policy.version,
                    "effective_from": policy.effective_from.isoformat() if policy.effective_from else None,
                    "effective_to": policy.effective_to.isoformat() if policy.effective_to else None,
                    "similarity": round(sim, 4),
                    "source": f"[Source: {policy.source_file}]",
                })
            return results
        except Exception as e:
            logger.info("Native pgvector operator unavailable (%s). Using in-process cosine similarity.", e)

    # 2. In-process vector cosine similarity
    stmt = select(Policy)
    if conditions:
        stmt = stmt.where(and_(*conditions))

    result = await session.execute(stmt)
    policies = result.scalars().all()

    if not policies:
        return []

    scored_policies = []
    q_vec = np.array(query_list, dtype=np.float32)
    q_norm = np.linalg.norm(q_vec) or 1.0

    for policy in policies:
        emb = policy.embedding
        if not emb:
            continue
        p_vec = np.array(emb, dtype=np.float32)
        p_norm = np.linalg.norm(p_vec) or 1.0
        cos_sim = float(np.dot(q_vec, p_vec) / (q_norm * p_norm))
        scored_policies.append((policy, cos_sim))

    # Sort descending by similarity
    scored_policies.sort(key=lambda x: x[1], reverse=True)
    top_records = scored_policies[:top_k]

    return [
        {
            "id": p.id,
            "title": p.title,
            "content": p.content,
            "format": p.format,
            "source_file": p.source_file,
            "version": p.version,
            "effective_from": p.effective_from.isoformat() if p.effective_from else None,
            "effective_to": p.effective_to.isoformat() if p.effective_to else None,
            "similarity": round(max(0.0, min(1.0, sim)), 4),
            "source": f"[Source: {p.source_file}]",
        }
        for p, sim in top_records
    ]
