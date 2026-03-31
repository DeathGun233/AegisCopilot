from __future__ import annotations

import json
from pathlib import Path

from ..config import settings
from ..models import RetrievalSettings, RetrievalStrategy


class RuntimeRetrievalService:
    def __init__(self, storage_path: Path) -> None:
        self.storage_path = storage_path
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def get_settings(self) -> RetrievalSettings:
        payload = self._load_payload()
        strategy = payload.get("strategy", RetrievalStrategy.hybrid.value)
        try:
            strategy_value = RetrievalStrategy(strategy)
        except ValueError:
            strategy_value = RetrievalStrategy.hybrid
        return RetrievalSettings(
            strategy=strategy_value,
            top_k=int(payload.get("top_k", settings.default_retrieval_top_k)),
            candidate_k=int(payload.get("candidate_k", settings.default_retrieval_candidate_k)),
            keyword_weight=float(payload.get("keyword_weight", settings.default_keyword_weight)),
            semantic_weight=float(payload.get("semantic_weight", settings.default_semantic_weight)),
            rerank_weight=float(payload.get("rerank_weight", settings.default_rerank_weight)),
            min_score=float(payload.get("min_score", settings.default_retrieval_min_score)),
        )

    def update_settings(self, **updates: object) -> RetrievalSettings:
        current = self.get_settings()
        merged = current.model_copy(
            update={key: value for key, value in updates.items() if value is not None},
        )
        self._validate(merged)
        self.storage_path.write_text(merged.model_dump_json(indent=2), encoding="utf-8")
        return merged

    def _load_payload(self) -> dict[str, object]:
        if not self.storage_path.exists():
            return {}
        try:
            return json.loads(self.storage_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _validate(payload: RetrievalSettings) -> None:
        if payload.top_k < 1 or payload.top_k > 10:
            raise ValueError("top_k 需在 1 到 10 之间")
        if payload.candidate_k < payload.top_k or payload.candidate_k > 40:
            raise ValueError("candidate_k 需大于等于 top_k，且不超过 40")
        if payload.keyword_weight < 0 or payload.semantic_weight < 0 or payload.rerank_weight < 0:
            raise ValueError("检索权重不能为负数")
        if payload.keyword_weight + payload.semantic_weight <= 0:
            raise ValueError("关键词权重与语义权重不能同时为 0")
        if payload.min_score < 0 or payload.min_score > 1:
            raise ValueError("min_score 需在 0 到 1 之间")
