from __future__ import annotations

import json
from typing import Any
from urllib import error, request

from ..config import Settings
from ..models import RetrievalResult


class RerankService:
    def __init__(
        self,
        *,
        provider: str = "heuristic",
        model: str = "qwen3-vl-rerank",
        base_url: str = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
        api_key: str = "",
        top_n: int = 40,
        timeout_seconds: float = 15,
    ) -> None:
        self.provider = provider.strip().lower() or "heuristic"
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.top_n = top_n
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_settings(cls, settings: Settings) -> "RerankService":
        return cls(
            provider=settings.rerank_provider,
            model=settings.rerank_model,
            base_url=settings.rerank_base_url,
            api_key=settings.rerank_api_key,
            top_n=settings.rerank_top_n,
            timeout_seconds=settings.rerank_timeout_seconds,
        )

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, object]],
        rerank_weight: float,
    ) -> list[RetrievalResult]:
        if not candidates:
            return []
        if self.provider in {"qwen", "dashscope"}:
            if not self.api_key:
                return self._heuristic_rerank(
                    candidates,
                    rerank_weight,
                    source="heuristic-fallback",
                    error_message="missing rerank api key",
                )
            try:
                return self._qwen_rerank(query, candidates)
            except Exception as exc:
                return self._heuristic_rerank(
                    candidates,
                    rerank_weight,
                    source="heuristic-fallback",
                    error_message=str(exc),
                )
        return self._heuristic_rerank(candidates, rerank_weight)

    def _qwen_rerank(self, query: str, candidates: list[dict[str, object]]) -> list[RetrievalResult]:
        documents = [str(item["chunk"].text) for item in candidates]
        remote_scores = self._call_qwen(query, documents)
        if len(remote_scores) != len(candidates):
            raise RuntimeError("qwen rerank response score count does not match candidates")

        reranked: list[RetrievalResult] = []
        for item, qwen_score in zip(candidates, remote_scores):
            metadata_score = float(item.get("metadata_score", 0.0))
            final_score = min(1.0, max(0.0, qwen_score) * 0.9 + metadata_score * 0.1)
            reranked.append(
                self._to_result(
                    item,
                    score=round(final_score, 4),
                    rerank_score=round(max(0.0, qwen_score), 4),
                    rerank_source="qwen",
                    rerank_model=self.model,
                )
            )

        reranked.sort(
            key=lambda item: (item.score, item.rerank_score, item.keyword_score, item.semantic_score),
            reverse=True,
        )
        return reranked

    def _call_qwen(self, query: str, documents: list[str]) -> list[float]:
        payload = {
            "model": self.model,
            "input": {
                "query": {"text": query},
                "documents": [{"text": document} for document in documents],
            },
            "parameters": {
                "top_n": min(len(documents), max(self.top_n, 1)),
                "return_documents": False,
            },
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        http_request = request.Request(
            self.base_url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"qwen rerank http {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"qwen rerank request failed: {exc.reason}") from exc

        parsed = json.loads(response_body)
        if parsed.get("code"):
            raise RuntimeError(str(parsed.get("message") or parsed.get("code")))

        raw_results = parsed.get("output", {}).get("results", [])
        scores = [0.0 for _ in documents]
        for result in raw_results:
            index = int(result["index"])
            if 0 <= index < len(scores):
                scores[index] = float(result.get("relevance_score", 0.0))
        return scores

    def _heuristic_rerank(
        self,
        candidates: list[dict[str, object]],
        rerank_weight: float,
        *,
        source: str = "heuristic",
        error_message: str = "",
    ) -> list[RetrievalResult]:
        rerank_factor = min(max(rerank_weight, 0.0), 1.0)
        reranked: list[RetrievalResult] = []
        for item in candidates:
            hybrid_score = float(item["hybrid_score"])
            coverage_score = float(item["coverage_score"])
            keyword_score = float(item["keyword_score"])
            semantic_score = float(item["semantic_score"])
            metadata_score = float(item.get("metadata_score", 0.0))
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
                    + metadata_score * 0.1
                    + title_bonus * 0.08
                    + phrase_bonus * 0.07
                )
                * rerank_factor,
            )
            reranked.append(
                self._to_result(
                    item,
                    score=round(rerank_score, 4),
                    rerank_score=round(rerank_score, 4),
                    rerank_source=source,
                    rerank_error=error_message,
                )
            )

        reranked.sort(
            key=lambda item: (item.rerank_score, item.keyword_score, item.semantic_score),
            reverse=True,
        )
        return reranked

    @staticmethod
    def _to_result(
        item: dict[str, object],
        *,
        score: float,
        rerank_score: float,
        rerank_source: str,
        rerank_model: str = "",
        rerank_error: str = "",
    ) -> RetrievalResult:
        chunk = item["chunk"]
        return RetrievalResult(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            document_title=chunk.document_title,
            text=chunk.text,
            score=score,
            source=f"{chunk.document_title}#chunk-{chunk.chunk_index}",
            display_source=RerankService._display_source(chunk),
            retrieval_method="hybrid",
            keyword_score=round(float(item["keyword_score"]), 4),
            semantic_score=round(float(item["semantic_score"]), 4),
            semantic_source=str(item["semantic_source"]),
            rerank_score=rerank_score,
            rerank_source=rerank_source,
            rerank_model=rerank_model,
            rerank_error=rerank_error,
            coverage_score=round(float(item["coverage_score"]), 4),
            matched_query="",
            query_variant="primary",
            query_boost=1.0,
            metadata=dict(chunk.metadata),
        )

    @staticmethod
    def _display_source(chunk: Any) -> str:
        section_path = chunk.metadata.get("section_path", "")
        if isinstance(section_path, str) and section_path:
            return f"{chunk.document_title} | {section_path} | chunk {chunk.chunk_index + 1}"
        return f"{chunk.document_title} | chunk {chunk.chunk_index + 1}"
