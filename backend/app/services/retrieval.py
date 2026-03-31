from __future__ import annotations

from collections import Counter

from ..config import settings
from ..models import RetrievalResult
from ..repositories import DocumentRepository
from .text import tokenize


class RetrievalService:
    def __init__(self, repo: DocumentRepository) -> None:
        self.repo = repo

    def search(self, query: str, top_k: int | None = None) -> list[RetrievalResult]:
        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        top_k = top_k or settings.default_retrieval_top_k
        query_counter = Counter(query_tokens)
        results: list[RetrievalResult] = []
        for chunk in self.repo.list_chunks():
            chunk_counter = Counter(chunk.tokens)
            overlap = sum(min(query_counter[token], chunk_counter[token]) for token in query_counter)
            if overlap == 0:
                continue
            keyword_score = overlap / max(len(set(query_tokens)), 1)
            density_bonus = overlap / max(len(chunk.tokens), 1)
            score = round(keyword_score * 0.8 + density_bonus * 0.2, 4)
            results.append(
                RetrievalResult(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    document_title=chunk.document_title,
                    text=chunk.text,
                    score=score,
                    source=f"{chunk.document_title}#chunk-{chunk.chunk_index}",
                    display_source=f"{chunk.document_title} | chunk {chunk.chunk_index + 1}",
                )
            )

        results.sort(key=lambda item: item.score, reverse=True)
        return results[:top_k]
