"""
Okapi BM25 Ranking Algorithm Implementation

Provides keyword/lexical retrieval complementary to dense embeddings.
Includes tokenization, case-normalization, punctuation removal, and
standard Okapi BM25 scoring with parameters k1=1.5 and b=0.75.
"""

import math
import re
from typing import Any


def tokenize(text: str) -> list[str]:
    """Lowercase and extract alphanumeric word tokens."""
    return re.findall(r"\b[a-zA-Z0-9_-]+\b", text.lower())


class BM25Index:
    """In-memory Okapi BM25 index for policy chunks."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus_size = 0
        self.avg_doc_len = 0.0
        self.doc_lengths: list[int] = []
        self.doc_ids: list[str] = []
        self.documents: list[str] = []
        self.metadatas: list[dict[str, Any]] = []
        self.doc_freqs: dict[str, int] = {}  # term -> document frequency
        self.idf: dict[str, float] = {}

    def fit(
        self,
        doc_ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        """Index a collection of documents."""
        self.doc_ids = doc_ids
        self.documents = documents
        self.metadatas = metadatas
        self.corpus_size = len(documents)

        if self.corpus_size == 0:
            return

        total_length = 0
        self.doc_lengths = []
        self.doc_freqs = {}

        # First pass: count frequencies
        tokenized_corpus = []
        for doc in documents:
            tokens = tokenize(doc)
            self.doc_lengths.append(len(tokens))
            total_length += len(tokens)
            tokenized_corpus.append(tokens)

            # Count unique terms in this doc
            unique_terms = set(tokens)
            for term in unique_terms:
                self.doc_freqs[term] = self.doc_freqs.get(term, 0) + 1

        self.avg_doc_len = total_length / self.corpus_size

        # Compute Robertson-Spärck Jones IDF
        self.idf = {}
        for term, df in self.doc_freqs.items():
            # BM25 standard IDF with smoothing to prevent negative values
            val = (self.corpus_size - df + 0.5) / (df + 0.5)
            self.idf[term] = max(0.01, math.log(1.0 + val))

    def search(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        """Search indexed documents by BM25 score."""
        if self.corpus_size == 0:
            return []

        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        scores: list[float] = [0.0] * self.corpus_size

        for i, doc in enumerate(self.documents):
            doc_tokens = tokenize(doc)
            doc_len = self.doc_lengths[i]
            term_counts: dict[str, int] = {}
            for t in doc_tokens:
                term_counts[t] = term_counts.get(t, 0) + 1

            doc_score = 0.0
            for q_term in query_tokens:
                if q_term not in self.idf:
                    continue
                tf = term_counts.get(q_term, 0)
                if tf == 0:
                    continue
                idf = self.idf[q_term]
                # BM25 TF formula
                num = tf * (self.k1 + 1.0)
                denom = tf + self.k1 * (1.0 - self.b + self.b * (doc_len / self.avg_doc_len))
                doc_score += idf * (num / denom)

            scores[i] = doc_score

        # Rank documents
        ranked_indices = sorted(
            range(self.corpus_size), key=lambda idx: scores[idx], reverse=True
        )

        results = []
        max_score = max(scores) if scores and max(scores) > 0 else 1.0

        for idx in ranked_indices[:top_k]:
            raw_score = scores[idx]
            if raw_score <= 0.0:
                continue
            # Normalize to 0..1 scale for consistency
            norm_score = round(min(1.0, raw_score / max_score), 4)
            results.append({
                "id": self.doc_ids[idx],
                "text": self.documents[idx],
                "metadata": self.metadatas[idx],
                "score": norm_score,
                "raw_score": round(raw_score, 4),
            })

        return results


# Global singleton BM25 index
_bm25_index: BM25Index | None = None


def get_bm25_index() -> BM25Index:
    global _bm25_index
    if _bm25_index is None:
        _bm25_index = BM25Index()
    return _bm25_index

