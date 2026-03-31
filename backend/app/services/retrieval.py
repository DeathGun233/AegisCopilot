from __future__ import annotations

import math
import re
from collections import Counter

from ..models import RetrievalResult
from ..repositories import DocumentRepository
from .runtime_retrieval import RuntimeRetrievalService
from .text import normalize_text, tokenize


class RetrievalService:
    def __init__(self, repo: DocumentRepository, runtime_retrieval: RuntimeRetrievalService) -> None:
        self.repo = repo
        self.runtime_retrieval = runtime_retrieval

    def search(self, query: str, top_k: int | None = None) -> list[RetrievalResult]:
        normalized_query = normalize_text(query).lower()
        query_tokens = tokenize(normalized_query)
        if not query_tokens:
            return []

        settings = self.runtime_retrieval.get_settings()
        final_top_k = top_k or settings.top_k
        query_counter = Counter(query_tokens)
        query_ngrams = self._char_ngrams(normalized_query)

        keyword_weight, semantic_weight = self._normalize_pair(
            settings.keyword_weight,
            settings.semantic_weight,
        )

        candidates: list[dict[str, object]] = []
        for chunk in self.repo.list_chunks():
            chunk_text = normalize_text(chunk.text).lower()
            chunk_counter = Counter(chunk.tokens)
            overlap = sum(min(query_counter[token], chunk_counter[token]) for token in query_counter)
            coverage = overlap / max(len(query_counter), 1)
            density = overlap / max(len(chunk.tokens), 1)

            title_tokens = tokenize(chunk.document_title.lower())
            title_overlap = sum(1 for token in set(query_tokens) if token in title_tokens)
            title_bonus = min(title_overlap / max(len(set(query_tokens)), 1), 1.0)

            exact_phrase_bonus = 1.0 if normalized_query and normalized_query in chunk_text else 0.0
            keyword_score = min(
                1.0,
                coverage * 0.55 + density * 0.18 + title_bonus * 0.12 + exact_phrase_bonus * 0.15,
            )

            chunk_ngrams = self._char_ngrams(chunk_text)
            semantic_cosine = self._cosine_similarity(query_ngrams, chunk_ngrams)
            token_jaccard = self._jaccard_similarity(set(query_tokens), set(chunk.tokens))
            semantic_score = min(1.0, semantic_cosine * 0.72 + token_jaccard * 0.28)

            hybrid_score = keyword_score * keyword_weight + semantic_score * semantic_weight
            if hybrid_score < settings.min_score and exact_phrase_bonus == 0.0:
                continue

            candidates.append(
                {
                    "chunk": chunk,
                    "keyword_score": round(keyword_score, 4),
                    "semantic_score": round(semantic_score, 4),
                    "hybrid_score": round(hybrid_score, 4),
                    "coverage_score": round(coverage, 4),
                    "title_bonus": round(title_bonus, 4),
                    "phrase_bonus": round(exact_phrase_bonus, 4),
                }
            )

        candidates.sort(
            key=lambda item: (
                float(item["hybrid_score"]),
                float(item["coverage_score"]),
                float(item["keyword_score"]),
            ),
            reverse=True,
        )
        shortlist = candidates[: settings.candidate_k]
        reranked = self._rerank(shortlist, settings.rerank_weight)
        deduped = self._dedupe_results(reranked)
        return deduped[:final_top_k]

    def get_runtime_settings(self):
        return self.runtime_retrieval.get_settings()

    def update_runtime_settings(self, **updates: object):
        return self.runtime_retrieval.update_settings(**updates)

    def _rerank(self, candidates: list[dict[str, object]], rerank_weight: float) -> list[RetrievalResult]:
        rerank_factor = min(max(rerank_weight, 0.0), 1.0)
        reranked: list[RetrievalResult] = []
        for index, item in enumerate(candidates):
            chunk = item["chunk"]
            hybrid_score = float(item["hybrid_score"])
            coverage_score = float(item["coverage_score"])
            keyword_score = float(item["keyword_score"])
            semantic_score = float(item["semantic_score"])
            title_bonus = float(item["title_bonus"])
            phrase_bonus = float(item["phrase_bonus"])

            rerank_score = min(
                1.0,
                hybrid_score * (1 - rerank_factor)
                + (
                    hybrid_score * 0.35
                    + coverage_score * 0.2
                    + keyword_score * 0.18
                    + semantic_score * 0.12
                    + title_bonus * 0.08
                    + phrase_bonus * 0.07
                )
                * rerank_factor,
            )

            reranked.append(
                RetrievalResult(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    document_title=chunk.document_title,
                    text=chunk.text,
                    score=round(rerank_score, 4),
                    source=f"{chunk.document_title}#chunk-{chunk.chunk_index}",
                    display_source=f"{chunk.document_title} | 片段 {chunk.chunk_index + 1}",
                    retrieval_method="hybrid",
                    keyword_score=round(keyword_score, 4),
                    semantic_score=round(semantic_score, 4),
                    rerank_score=round(rerank_score, 4),
                    coverage_score=round(coverage_score, 4),
                )
            )

        reranked.sort(
            key=lambda item: (item.rerank_score, item.keyword_score, item.semantic_score),
            reverse=True,
        )
        return reranked

    @staticmethod
    def _dedupe_results(results: list[RetrievalResult]) -> list[RetrievalResult]:
        seen_signatures: set[str] = set()
        deduped: list[RetrievalResult] = []
        for item in results:
            signature = f"{item.document_id}:{normalize_text(item.text)[:120].lower()}"
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            deduped.append(item)
        return deduped

    @staticmethod
    def _char_ngrams(text: str, min_n: int = 2, max_n: int = 3) -> Counter[str]:
        compact = re.sub(r"\s+", "", text)
        grams: Counter[str] = Counter()
        for size in range(min_n, max_n + 1):
            if len(compact) < size:
                continue
            for index in range(len(compact) - size + 1):
                grams[compact[index : index + size]] += 1
        return grams

    @staticmethod
    def _cosine_similarity(left: Counter[str], right: Counter[str]) -> float:
        if not left or not right:
            return 0.0
        dot = sum(left[token] * right.get(token, 0) for token in left)
        if dot <= 0:
            return 0.0
        left_norm = math.sqrt(sum(value * value for value in left.values()))
        right_norm = math.sqrt(sum(value * value for value in right.values()))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return dot / (left_norm * right_norm)

    @staticmethod
    def _jaccard_similarity(left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left & right) / max(len(left | right), 1)

    @staticmethod
    def _normalize_pair(left: float, right: float) -> tuple[float, float]:
        total = left + right
        if total <= 0:
            return 0.5, 0.5
        return left / total, right / total
