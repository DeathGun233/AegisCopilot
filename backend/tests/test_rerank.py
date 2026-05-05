from __future__ import annotations

from app import config
from app.config import Settings
from app.models import Chunk, RetrievalResult
from app.services.rerank import RerankService


def _chunk(
    chunk_id: str,
    text: str,
    *,
    metadata: dict[str, object] | None = None,
    chunk_index: int = 0,
) -> Chunk:
    return Chunk(
        id=chunk_id,
        document_id="doc-logistics",
        document_title="Cross-border logistics rules",
        text=text,
        chunk_index=chunk_index,
        tokens=[token.lower() for token in text.replace(",", " ").replace(".", " ").split()],
        metadata=metadata or {},
    )


def _candidate(
    chunk: Chunk,
    *,
    hybrid_score: float = 0.6,
    coverage_score: float = 0.5,
    keyword_score: float = 0.5,
    semantic_score: float = 0.5,
    metadata_score: float = 0.0,
) -> dict[str, object]:
    return {
        "chunk": chunk,
        "hybrid_score": hybrid_score,
        "coverage_score": coverage_score,
        "keyword_score": keyword_score,
        "semantic_score": semantic_score,
        "semantic_source": "heuristic",
        "metadata_score": metadata_score,
        "title_bonus": 0.0,
        "phrase_bonus": 0.0,
    }


def test_rerank_settings_default_to_qwen() -> None:
    settings = Settings()

    assert settings.rerank_provider == "qwen"
    assert settings.rerank_model == "qwen3-rerank"
    assert settings.rerank_top_n == 40
    assert settings.rerank_base_url.endswith("/api/v1/services/rerank/text-rerank/text-rerank")


def test_rerank_api_key_does_not_reuse_general_llm_keys(monkeypatch) -> None:
    monkeypatch.delenv("AEGIS_RERANK_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setenv("AEGIS_LLM_API_KEY", "llm-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")

    assert config._pick_rerank_api_key() == ""


def test_rerank_api_key_accepts_dashscope_specific_keys(monkeypatch) -> None:
    monkeypatch.delenv("AEGIS_RERANK_API_KEY", raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-key")

    assert config._pick_rerank_api_key() == "dashscope-key"


def test_retrieval_result_has_rerank_source_defaults() -> None:
    result = RetrievalResult(
        chunk_id="chunk-1",
        document_id="doc-1",
        document_title="Doc",
        text="text",
        score=0.1,
        source="Doc#chunk-0",
    )

    assert result.rerank_source == "heuristic"
    assert result.rerank_model == ""
    assert result.rerank_error == ""


def test_heuristic_rerank_preserves_existing_score_order() -> None:
    germany = _chunk(
        "chunk-de",
        "Germany DDP battery rules",
        metadata={"country": "DE", "incoterm": "DDP", "product_category": "battery"},
    )
    france = _chunk(
        "chunk-fr",
        "France DDP liquid rules",
        metadata={"country": "FR", "incoterm": "DDP", "product_category": "liquid"},
        chunk_index=1,
    )
    candidates = [
        _candidate(france, hybrid_score=0.45, coverage_score=0.4, keyword_score=0.4, semantic_score=0.4),
        _candidate(germany, hybrid_score=0.75, coverage_score=0.7, keyword_score=0.8, semantic_score=0.6),
    ]

    results = RerankService(provider="heuristic").rerank("Germany DDP battery", candidates, rerank_weight=0.6)

    assert [item.chunk_id for item in results] == ["chunk-de", "chunk-fr"]
    assert results[0].rerank_source == "heuristic"
    assert results[0].rerank_model == ""
    assert results[0].rerank_error == ""


def test_qwen_rerank_uses_remote_scores(monkeypatch) -> None:
    france = _chunk("chunk-fr", "France DDP liquid rules", chunk_index=0)
    germany = _chunk("chunk-de", "Germany DDP battery rules", chunk_index=1)
    candidates = [
        _candidate(france, hybrid_score=0.8, metadata_score=0.0),
        _candidate(germany, hybrid_score=0.6, metadata_score=1.0),
    ]

    def fake_call(self, query, documents):
        return [0.1, 0.95]

    monkeypatch.setattr(RerankService, "_call_qwen", fake_call)

    service = RerankService(provider="qwen", model="qwen3-vl-rerank", api_key="test-key")
    results = service.rerank("Germany DDP battery", candidates, rerank_weight=0.6)

    assert [item.chunk_id for item in results] == ["chunk-de", "chunk-fr"]
    assert results[0].rerank_source == "qwen"
    assert results[0].rerank_model == "qwen3-vl-rerank"
    assert results[0].rerank_error == ""


def test_qwen_rerank_falls_back_to_heuristic_on_error(monkeypatch) -> None:
    chunk = _chunk("chunk-a", "Germany DDP battery rules")
    candidates = [_candidate(chunk, hybrid_score=0.7)]

    def fail_call(self, query, documents):
        raise RuntimeError("remote down")

    monkeypatch.setattr(RerankService, "_call_qwen", fail_call)

    service = RerankService(provider="qwen", model="qwen3-vl-rerank", api_key="test-key")
    results = service.rerank("Germany DDP battery", candidates, rerank_weight=0.6)

    assert results[0].rerank_source == "heuristic-fallback"
    assert "remote down" in results[0].rerank_error


def test_qwen_rerank_without_explicit_key_does_not_call_remote(monkeypatch) -> None:
    chunk = _chunk("chunk-a", "Germany DDP battery rules")
    candidates = [_candidate(chunk, hybrid_score=0.7)]

    def fail_call(self, query, documents):
        raise AssertionError("Qwen rerank should not be called without a rerank key")

    monkeypatch.setattr(RerankService, "_call_qwen", fail_call)

    service = RerankService(provider="qwen", model="qwen3-rerank", api_key="")
    results = service.rerank("Germany DDP battery", candidates, rerank_weight=0.6)

    assert results[0].rerank_source == "heuristic-fallback"
    assert "missing" in results[0].rerank_error
    assert "DashScope" in results[0].rerank_error


def test_qwen_score_is_soft_adjusted_by_logistics_metadata(monkeypatch) -> None:
    france = _chunk(
        "chunk-fr-liquid",
        "France DDP liquid product customs rules",
        metadata={"country": "FR", "region": "EU", "incoterm": "DDP", "product_category": "liquid"},
    )
    germany = _chunk(
        "chunk-de-battery",
        "Germany DDP battery product customs rules",
        metadata={"country": "DE", "region": "EU", "incoterm": "DDP", "product_category": "battery"},
        chunk_index=1,
    )
    candidates = [
        _candidate(france, hybrid_score=0.8, metadata_score=0.0),
        _candidate(germany, hybrid_score=0.7, metadata_score=1.0),
    ]

    def fake_call(self, query, documents):
        return [0.91, 0.88]

    monkeypatch.setattr(RerankService, "_call_qwen", fake_call)

    service = RerankService(provider="qwen", model="qwen3-vl-rerank", api_key="test-key")
    results = service.rerank("Germany DDP battery products", candidates, rerank_weight=0.6)

    assert results[0].chunk_id == "chunk-de-battery"


def test_qwen_rerank_documents_include_metadata_context(monkeypatch) -> None:
    chunk = _chunk(
        "chunk-row",
        "要求：需要 MSDS、UN38.3、运输鉴定书",
        metadata={
            "section_path": "欧洲 DDP 渠道清关资料表 > 德国 > 带电产品",
            "table_name": "带电产品",
            "row_id": "row-de-ddp-battery",
            "effective_date": "2026-05-01",
            "country": "DE",
        },
    )
    captured: dict[str, list[str]] = {}

    def fake_call(self, query, documents):
        captured["documents"] = documents
        return [0.8]

    monkeypatch.setattr(RerankService, "_call_qwen", fake_call)

    service = RerankService(provider="qwen", model="qwen3-rerank", api_key="dashscope-key")
    service.rerank("德国 DDP 带电产品清关资料", [_candidate(chunk)], rerank_weight=0.6)

    document = captured["documents"][0]
    assert "Cross-border logistics rules" in document
    assert "欧洲 DDP 渠道清关资料表 > 德国 > 带电产品" in document
    assert "带电产品" in document
    assert "row-de-ddp-battery" in document
    assert "2026-05-01" in document
    assert "要求：需要 MSDS、UN38.3、运输鉴定书" in document
