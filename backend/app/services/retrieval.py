from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from ..config import settings
from ..models import RetrievalResult, RetrievalSettings
from ..repositories import DocumentRepository
from ..vector_store import VectorStore
from .embeddings import EmbeddingService
from .runtime_retrieval import RuntimeRetrievalService
from .text import normalize_text, tokenize


@dataclass(frozen=True)
class QueryVariant:
    query: str
    label: str
    boost: float


class BM25KeywordIndex:
    def __init__(self, chunks: list, *, extra_text_builder=None) -> None:
        self.chunks_by_id = {chunk.id: chunk for chunk in chunks}
        self.inverted_index: dict[str, dict[str, int]] = defaultdict(dict)
        self.document_lengths: dict[str, int] = {}
        self.document_frequency: Counter[str] = Counter()
        self.average_document_length = 0.0
        self.extra_text_builder = extra_text_builder or (lambda chunk: "")
        self._build(chunks)

    def search(self, query: str, limit: int) -> list:
        if limit <= 0 or not self.chunks_by_id:
            return []
        query_terms = self._terms_for_text(normalize_text(query).lower())
        if not query_terms:
            return []

        scores: dict[str, float] = defaultdict(float)
        matched_terms: dict[str, set[str]] = defaultdict(set)
        unique_query_terms = set(query_terms)
        for term in unique_query_terms:
            postings = self.inverted_index.get(term)
            if not postings:
                continue
            idf = self._idf(term)
            for chunk_id, frequency in postings.items():
                scores[chunk_id] += idf * self._term_score(
                    frequency,
                    self.document_lengths.get(chunk_id, 0),
                )
                matched_terms[chunk_id].add(term)

        for chunk_id in list(scores):
            coverage = len(matched_terms[chunk_id]) / max(len(unique_query_terms), 1)
            scores[chunk_id] *= coverage * coverage

        ranked = sorted(
            scores.items(),
            key=lambda item: (
                item[1],
                self.chunks_by_id[item[0]].chunk_index * -1,
            ),
            reverse=True,
        )
        return [self.chunks_by_id[chunk_id] for chunk_id, _ in ranked[:limit]]

    def _build(self, chunks: list) -> None:
        total_length = 0
        for chunk in chunks:
            terms = self._chunk_terms(chunk)
            term_counts = Counter(terms)
            self.document_lengths[chunk.id] = len(terms)
            total_length += len(terms)
            for term, frequency in term_counts.items():
                self.inverted_index[term][chunk.id] = frequency
                self.document_frequency[term] += 1
        self.average_document_length = total_length / max(len(chunks), 1)

    def _chunk_terms(self, chunk) -> list[str]:
        values = [
            *chunk.tokens,
            *self._terms_for_text(" ".join(chunk.tokens).lower()),
            *tokenize(chunk.document_title.lower()),
            *self._terms_for_text(chunk.document_title.lower()),
            *self._terms_for_text(normalize_text(self.extra_text_builder(chunk)).lower()),
        ]
        return [term for term in values if term]

    @staticmethod
    def _terms_for_text(text: str) -> list[str]:
        terms = tokenize(text)
        for span in re.findall(r"[\u4e00-\u9fff]{2,}", text):
            for size in range(3, min(6, len(span)) + 1):
                terms.extend(span[index : index + size] for index in range(len(span) - size + 1))
        return terms

    def _idf(self, term: str) -> float:
        total_documents = max(len(self.chunks_by_id), 1)
        frequency = self.document_frequency.get(term, 0)
        return math.log(1 + (total_documents - frequency + 0.5) / (frequency + 0.5))

    def _term_score(self, frequency: int, document_length: int) -> float:
        k1 = 1.5
        b = 0.75
        length_norm = document_length / max(self.average_document_length, 1.0)
        return (frequency * (k1 + 1)) / (frequency + k1 * (1 - b + b * length_norm))


class RetrievalService:
    def __init__(
        self,
        repo: DocumentRepository,
        vector_store: VectorStore,
        runtime_retrieval: RuntimeRetrievalService,
        embeddings: EmbeddingService,
    ) -> None:
        self.repo = repo
        self.vector_store = vector_store
        self.runtime_retrieval = runtime_retrieval
        self.embeddings = embeddings
        self._keyword_index_signature: tuple[tuple[str, int, int, str], ...] | None = None
        self._keyword_index: BM25KeywordIndex | None = None

    def search(
        self,
        query: str,
        top_k: int | None = None,
        query_variants: list[str] | None = None,
    ) -> list[RetrievalResult]:
        settings = self.runtime_retrieval.get_settings()
        final_top_k = top_k or settings.top_k
        variants = self._build_query_variants(query, query_variants)
        if not variants:
            return []

        per_query_limit = max(settings.candidate_k, final_top_k)
        merged: dict[str, RetrievalResult] = {}
        for variant in variants:
            for item in self._search_single_query(variant.query, settings, per_query_limit):
                final_score = round(min(1.0, item.score * variant.boost), 4)
                updated = item.model_copy(
                    update={
                        "score": final_score,
                        "matched_query": variant.query,
                        "query_variant": variant.label,
                        "query_boost": variant.boost,
                    }
                )
                current = merged.get(updated.chunk_id)
                if current is None or updated.score > current.score:
                    merged[updated.chunk_id] = updated

        deduped = self._dedupe_results(list(merged.values()))
        deduped.sort(
            key=lambda item: (item.score, item.keyword_score, item.semantic_score, item.coverage_score),
            reverse=True,
        )
        expanded = self._expand_context_results(deduped, final_top_k)
        return expanded[:final_top_k]

    def _search_single_query(self, query: str, settings, limit: int) -> list[RetrievalResult]:
        candidates = [
            item
            for item in self._score_single_query_candidates(query, settings, limit)
            if item["filter_reason"] == "candidate"
        ]
        shortlist = candidates[: settings.candidate_k]
        reranked = self._rerank(shortlist, settings.rerank_weight)
        deduped = self._dedupe_results(reranked)
        return deduped[:limit]

    def debug_search(
        self,
        query: str,
        top_k: int | None = None,
        candidate_k: int | None = None,
        keyword_weight: float | None = None,
        semantic_weight: float | None = None,
        rerank_weight: float | None = None,
        min_score: float | None = None,
        query_variants: list[str] | None = None,
    ) -> dict[str, Any]:
        settings = self._build_trial_settings(
            top_k=top_k,
            candidate_k=candidate_k,
            keyword_weight=keyword_weight,
            semantic_weight=semantic_weight,
            rerank_weight=rerank_weight,
            min_score=min_score,
        )
        final_top_k = settings.top_k
        variants = self._build_query_variants(query, query_variants)
        if not variants:
            return {
                "query": normalize_text(query),
                "settings": settings.model_dump(mode="json"),
                "query_variants": [],
                "candidates": [],
                "results": [],
            }

        per_query_limit = max(settings.candidate_k, final_top_k)
        debug_candidates: list[dict[str, Any]] = []
        result_records: list[dict[str, Any]] = []
        candidate_by_key: dict[tuple[str, str], dict[str, Any]] = {}

        for variant in variants:
            scored_candidates = self._score_single_query_candidates(variant.query, settings, per_query_limit)
            eligible_candidates = [item for item in scored_candidates if item["filter_reason"] == "candidate"]
            shortlist = eligible_candidates[: settings.candidate_k]
            outside_candidate_k = eligible_candidates[settings.candidate_k :]

            for item in scored_candidates:
                if item["filter_reason"] == "below_min_score":
                    debug_candidates.append(self._debug_item_from_scored(item, variant, "below_min_score"))

            for item in outside_candidate_k:
                debug_candidates.append(self._debug_item_from_scored(item, variant, "outside_candidate_k"))

            for item in self._rerank(shortlist, settings.rerank_weight):
                final_score = round(min(1.0, item.score * variant.boost), 4)
                updated = item.model_copy(
                    update={
                        "score": final_score,
                        "matched_query": variant.query,
                        "query_variant": variant.label,
                        "query_boost": variant.boost,
                    }
                )
                debug_item = self._debug_item_from_result(updated, "candidate")
                debug_candidates.append(debug_item)
                candidate_by_key[(variant.label, updated.chunk_id)] = debug_item
                result_records.append(
                    {
                        "result": updated,
                        "signature": f"{updated.document_id}:{normalize_text(updated.text)[:120].lower()}",
                        "variant_label": variant.label,
                    }
                )

        result_records.sort(
            key=lambda item: (
                item["result"].score,
                item["result"].keyword_score,
                item["result"].semantic_score,
                item["result"].coverage_score,
            ),
            reverse=True,
        )

        selected_results: list[RetrievalResult] = []
        seen_signatures: set[str] = set()
        for item in result_records:
            result = item["result"]
            debug_item = candidate_by_key.get((str(item["variant_label"]), result.chunk_id))
            signature = str(item["signature"])
            if signature in seen_signatures:
                if debug_item is not None:
                    debug_item["filter_reason"] = "duplicate"
                continue
            seen_signatures.add(signature)
            if len(selected_results) < final_top_k:
                selected_results.append(result)
                if debug_item is not None:
                    debug_item["filter_reason"] = "selected"
                    debug_item["rank"] = len(selected_results)
            elif debug_item is not None:
                debug_item["filter_reason"] = "outside_top_k"

        return {
            "query": normalize_text(query),
            "settings": settings.model_dump(mode="json"),
            "query_variants": [variant.__dict__ for variant in variants],
            "candidates": debug_candidates,
            "results": [
                self._debug_item_from_result(item, "selected", rank=index)
                for index, item in enumerate(self._expand_context_results(selected_results, final_top_k), start=1)
            ],
        }

    def _score_single_query_candidates(self, query: str, settings, limit: int) -> list[dict[str, object]]:
        normalized_query = normalize_text(query).lower()
        query_tokens = tokenize(normalized_query)
        if not query_tokens:
            return []

        query_counter = Counter(query_tokens)
        query_ngrams = self._char_ngrams(normalized_query)
        query_embedding = self.embeddings.embed_text(normalized_query) if self.embeddings.is_enabled() else []

        keyword_weight, semantic_weight = self._normalize_pair(
            settings.keyword_weight,
            settings.semantic_weight,
        )

        candidate_chunks = self._collect_candidate_chunks(
            normalized_query,
            query_tokens,
            query_embedding,
            settings,
            limit,
        )

        candidates: list[dict[str, object]] = []
        for chunk in candidate_chunks:
            chunk_text = normalize_text(self._chunk_search_text(chunk)).lower()
            chunk_counter = Counter([*chunk.tokens, *tokenize(self._section_search_text(chunk.metadata).lower())])
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

            token_jaccard = self._jaccard_similarity(set(query_tokens), set(chunk.tokens))
            semantic_source = "heuristic"
            if query_embedding and chunk.embedding and len(query_embedding) == len(chunk.embedding):
                vector_cosine = self._vector_cosine_similarity(query_embedding, chunk.embedding)
                semantic_score = min(1.0, vector_cosine * 0.85 + token_jaccard * 0.15)
                semantic_source = "embedding"
            else:
                chunk_ngrams = self._char_ngrams(chunk_text)
                semantic_cosine = self._cosine_similarity(query_ngrams, chunk_ngrams)
                semantic_score = min(1.0, semantic_cosine * 0.72 + token_jaccard * 0.28)

            hybrid_score = keyword_score * keyword_weight + semantic_score * semantic_weight
            filter_reason = "candidate"
            if hybrid_score < settings.min_score and exact_phrase_bonus == 0.0:
                filter_reason = "below_min_score"

            candidates.append(
                {
                    "chunk": chunk,
                    "keyword_score": round(keyword_score, 4),
                    "semantic_score": round(semantic_score, 4),
                    "semantic_source": semantic_source,
                    "hybrid_score": round(hybrid_score, 4),
                    "coverage_score": round(coverage, 4),
                    "title_bonus": round(title_bonus, 4),
                    "phrase_bonus": round(exact_phrase_bonus, 4),
                    "filter_reason": filter_reason,
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
        return candidates

    def _collect_candidate_chunks(
        self,
        normalized_query: str,
        query_tokens: list[str],
        query_embedding: list[float],
        settings,
        limit: int,
    ) -> list:
        vector_candidates = self.vector_store.search_candidates(normalized_query, query_embedding, limit)
        keyword_candidates = self._keyword_candidate_chunks(normalized_query, query_tokens, settings, limit)

        merged = []
        seen_ids: set[str] = set()
        for chunk in [*vector_candidates, *keyword_candidates]:
            if chunk.id in seen_ids:
                continue
            seen_ids.add(chunk.id)
            merged.append(chunk)
        return merged

    def _keyword_candidate_chunks(
        self,
        normalized_query: str,
        query_tokens: list[str],
        settings,
        limit: int,
    ) -> list:
        if not query_tokens:
            return []
        return self._get_keyword_index().search(normalized_query, max(settings.candidate_k, limit))

    def _get_keyword_index(self) -> BM25KeywordIndex:
        chunks = self.vector_store.list_chunks()
        signature = tuple(
            (chunk.id, chunk.chunk_index, len(chunk.text), chunk.embedding_version)
            for chunk in chunks
        )
        if self._keyword_index is None or self._keyword_index_signature != signature:
            self._keyword_index = BM25KeywordIndex(chunks, extra_text_builder=self._chunk_search_text)
            self._keyword_index_signature = signature
        return self._keyword_index

    def get_runtime_settings(self):
        return self.runtime_retrieval.get_settings()

    def update_runtime_settings(self, **updates: object):
        return self.runtime_retrieval.update_settings(**updates)

    def _build_trial_settings(self, **updates: object) -> RetrievalSettings:
        settings = self.runtime_retrieval.get_settings().model_copy(
            update={key: value for key, value in updates.items() if value is not None},
        )
        self._validate_settings(settings)
        return settings

    @staticmethod
    def _validate_settings(settings: RetrievalSettings) -> None:
        if settings.top_k < 1 or settings.top_k > 10:
            raise ValueError("top_k must be between 1 and 10")
        if settings.candidate_k < settings.top_k or settings.candidate_k > 40:
            raise ValueError("candidate_k must be greater than or equal to top_k and no more than 40")
        if settings.keyword_weight < 0 or settings.semantic_weight < 0 or settings.rerank_weight < 0:
            raise ValueError("retrieval weights cannot be negative")
        if settings.keyword_weight + settings.semantic_weight <= 0:
            raise ValueError("keyword_weight and semantic_weight cannot both be 0")
        if settings.min_score < 0 or settings.min_score > 1:
            raise ValueError("min_score must be between 0 and 1")

    @staticmethod
    def _build_query_variants(query: str, query_variants: list[str] | None) -> list[QueryVariant]:
        base = normalize_text(query)
        if not base:
            return []

        variants: list[QueryVariant] = [QueryVariant(query=base, label="primary", boost=1.0)]
        if not query_variants:
            return variants

        seen = {base.lower()}
        for index, item in enumerate(query_variants, start=1):
            normalized = normalize_text(item)
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            boost = max(0.72, 0.92 - (index - 1) * 0.06)
            variants.append(QueryVariant(query=normalized, label=f"expand_{index}", boost=round(boost, 2)))
        return variants

    def _rerank(self, candidates: list[dict[str, object]], rerank_weight: float) -> list[RetrievalResult]:
        rerank_factor = min(max(rerank_weight, 0.0), 1.0)
        reranked: list[RetrievalResult] = []
        for index, item in enumerate(candidates):
            chunk = item["chunk"]
            hybrid_score = float(item["hybrid_score"])
            coverage_score = float(item["coverage_score"])
            keyword_score = float(item["keyword_score"])
            semantic_score = float(item["semantic_score"])
            semantic_source = str(item["semantic_source"])
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
                    display_source=self._display_source(chunk),
                    retrieval_method="hybrid",
                    keyword_score=round(keyword_score, 4),
                    semantic_score=round(semantic_score, 4),
                    semantic_source=semantic_source,
                    rerank_score=round(rerank_score, 4),
                    coverage_score=round(coverage_score, 4),
                    matched_query="",
                    query_variant="primary",
                    query_boost=1.0,
                    metadata=dict(chunk.metadata),
                )
            )

        reranked.sort(
            key=lambda item: (item.rerank_score, item.keyword_score, item.semantic_score),
            reverse=True,
        )
        return reranked

    def _expand_context_results(self, results: list[RetrievalResult], limit: int) -> list[RetrievalResult]:
        expanded: list[RetrievalResult] = []
        seen_signatures: set[str] = set()

        def add_result(item: RetrievalResult) -> None:
            signature = item.chunk_id or self._result_signature(item)
            if signature in seen_signatures:
                return
            seen_signatures.add(signature)
            expanded.append(item)

        for result in results:
            add_result(result)
            if len(expanded) >= limit:
                break
            for section_result in self._same_section_chunk_results(result):
                add_result(section_result)
                if len(expanded) >= limit:
                    break
            if len(expanded) >= limit:
                break
            for adjacent in self._adjacent_chunk_results(result):
                add_result(adjacent)
                if len(expanded) >= limit:
                    break
            if len(expanded) >= limit:
                break

        return expanded

    def _same_section_chunk_results(self, result: RetrievalResult) -> list[RetrievalResult]:
        prefix = self._section_expansion_prefix(result.metadata)
        if not prefix:
            return []
        try:
            chunks = sorted(
                self.vector_store.list_chunks_for_document(result.document_id),
                key=lambda item: item.chunk_index,
            )
        except Exception:
            return []

        section_results: list[RetrievalResult] = []
        for chunk in chunks:
            if chunk.id == result.chunk_id:
                continue
            parts = self._section_path_parts(chunk.metadata)
            if len(parts) < len(prefix) or parts[: len(prefix)] != prefix:
                continue
            section_results.append(
                RetrievalResult(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    document_title=chunk.document_title,
                    text=chunk.text,
                    score=round(max(result.score - 0.01, settings.min_grounding_score), 4),
                    source=f"{chunk.document_title}#chunk-{chunk.chunk_index}",
                    display_source=self._display_source(chunk),
                    retrieval_method="section",
                    keyword_score=result.keyword_score,
                    semantic_score=result.semantic_score,
                    semantic_source=result.semantic_source,
                    rerank_score=result.rerank_score,
                    coverage_score=result.coverage_score,
                    matched_query=result.matched_query,
                    query_variant=result.query_variant,
                    query_boost=result.query_boost,
                    metadata=dict(chunk.metadata),
                )
            )
        return section_results

    def _adjacent_chunk_results(self, result: RetrievalResult) -> list[RetrievalResult]:
        try:
            chunks = sorted(
                self.vector_store.list_chunks_for_document(result.document_id),
                key=lambda item: item.chunk_index,
            )
        except Exception:
            return []

        by_index = {chunk.chunk_index: chunk for chunk in chunks}
        adjacent_results: list[RetrievalResult] = []
        for offset in (1, 2, -1):
            chunk = by_index.get(self._chunk_index_from_result(result) + offset)
            if chunk is None:
                continue
            adjacent_results.append(
                RetrievalResult(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    document_title=chunk.document_title,
                    text=chunk.text,
                    score=round(max(result.score - 0.02 * abs(offset), settings.min_grounding_score), 4),
                    source=f"{chunk.document_title}#chunk-{chunk.chunk_index}",
                    display_source=self._display_source(chunk),
                    retrieval_method="adjacent",
                    keyword_score=result.keyword_score,
                    semantic_score=result.semantic_score,
                    semantic_source=result.semantic_source,
                    rerank_score=result.rerank_score,
                    coverage_score=result.coverage_score,
                    matched_query=result.matched_query,
                    query_variant=result.query_variant,
                    query_boost=result.query_boost,
                    metadata=dict(chunk.metadata),
                )
            )
        return adjacent_results

    @staticmethod
    def _chunk_search_text(chunk) -> str:
        section_text = RetrievalService._section_search_text(chunk.metadata)
        if not section_text:
            return chunk.text
        return f"{section_text}\n{chunk.text}"

    @staticmethod
    def _section_search_text(metadata: dict[str, Any]) -> str:
        values: list[str] = []
        for key in ("section_path", "section_title", "section_parent_path", "section_root_title"):
            value = metadata.get(key)
            if isinstance(value, str) and value:
                values.append(value)
        return " ".join(values)

    @staticmethod
    def _display_source(chunk) -> str:
        section_path = chunk.metadata.get("section_path", "")
        if isinstance(section_path, str) and section_path:
            return f"{chunk.document_title} | {section_path} | 片段 {chunk.chunk_index + 1}"
        return f"{chunk.document_title} | 片段 {chunk.chunk_index + 1}"

    @staticmethod
    def _section_path_parts(metadata: dict[str, Any]) -> list[str]:
        parts = metadata.get("section_path_parts")
        if isinstance(parts, list):
            return [str(item) for item in parts if str(item)]
        section_path = metadata.get("section_path")
        if isinstance(section_path, str) and section_path:
            return [item.strip() for item in section_path.split(">") if item.strip()]
        return []

    @staticmethod
    def _section_expansion_prefix(metadata: dict[str, Any]) -> list[str]:
        parts = RetrievalService._section_path_parts(metadata)
        if not parts:
            return []
        return parts[:1]

    @staticmethod
    def _chunk_index_from_result(result: RetrievalResult) -> int:
        try:
            return int(result.source.rsplit("#chunk-", 1)[1])
        except (IndexError, ValueError):
            return 0

    @staticmethod
    def _debug_item_from_scored(item: dict[str, object], variant: QueryVariant, filter_reason: str) -> dict[str, Any]:
        chunk = item["chunk"]
        return {
            "chunk_id": chunk.id,
            "document_id": chunk.document_id,
            "document_title": chunk.document_title,
            "text": chunk.text,
            "score": float(item["hybrid_score"]),
            "source": f"{chunk.document_title}#chunk-{chunk.chunk_index}",
            "display_source": RetrievalService._display_source(chunk),
            "retrieval_method": "hybrid",
            "keyword_score": float(item["keyword_score"]),
            "semantic_score": float(item["semantic_score"]),
            "semantic_source": str(item["semantic_source"]),
            "rerank_score": 0.0,
            "coverage_score": float(item["coverage_score"]),
            "matched_query": variant.query,
            "query_variant": variant.label,
            "query_boost": variant.boost,
            "filter_reason": filter_reason,
            "rank": None,
            "metadata": dict(chunk.metadata),
            "section_path": chunk.metadata.get("section_path", ""),
        }

    @staticmethod
    def _debug_item_from_result(item: RetrievalResult, filter_reason: str, rank: int | None = None) -> dict[str, Any]:
        return {
            "chunk_id": item.chunk_id,
            "document_id": item.document_id,
            "document_title": item.document_title,
            "text": item.text,
            "score": item.score,
            "source": item.source,
            "display_source": item.display_source,
            "retrieval_method": item.retrieval_method,
            "keyword_score": item.keyword_score,
            "semantic_score": item.semantic_score,
            "semantic_source": item.semantic_source,
            "rerank_score": item.rerank_score,
            "coverage_score": item.coverage_score,
            "matched_query": item.matched_query,
            "query_variant": item.query_variant,
            "query_boost": item.query_boost,
            "filter_reason": filter_reason,
            "rank": rank,
            "metadata": dict(item.metadata),
            "section_path": item.metadata.get("section_path", ""),
        }

    @staticmethod
    def _dedupe_results(results: list[RetrievalResult]) -> list[RetrievalResult]:
        seen_signatures: set[str] = set()
        deduped: list[RetrievalResult] = []
        for item in results:
            signature = RetrievalService._result_signature(item)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            deduped.append(item)
        return deduped

    @staticmethod
    def _result_signature(item: RetrievalResult) -> str:
        return normalize_text(item.text)[:180].lower()

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
    def _vector_cosine_similarity(left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        dot = sum(lv * rv for lv, rv in zip(left, right))
        if dot <= 0:
            return 0.0
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
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
