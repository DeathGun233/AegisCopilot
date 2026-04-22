from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models import Chunk, Document, DocumentIndexState, utc_now
from app.repositories import DocumentRepository
from app.services.runtime_retrieval import RuntimeRetrievalService


class DisabledEmbeddings:
    def is_enabled(self) -> bool:
        return False

    def embed_text(self, text: str) -> list[float]:
        raise AssertionError("disabled embeddings should not embed text")

    def get_version(self) -> str:
        return "disabled"


class RejectingDocumentRepository:
    def list_chunks(self) -> list[Chunk]:
        raise AssertionError("retrieval should read candidates from vector store")


class StaticVectorStore:
    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self.calls: list[dict[str, object]] = []

    def search_candidates(self, query: str, query_embedding: list[float], limit: int) -> list[Chunk]:
        self.calls.append({"query": query, "query_embedding": query_embedding, "limit": limit})
        return self.chunks


def test_retrieval_reads_candidates_from_vector_store(tmp_path: Path) -> None:
    from app.services.retrieval import RetrievalService

    chunk = Chunk(
        id="chunk-vector-1",
        document_id="doc-vector",
        document_title="Leave Policy",
        text="Employees submit leave requests one business day in advance.",
        chunk_index=0,
        tokens=["employees", "submit", "leave", "requests", "business", "day"],
        embedding=[],
        embedding_version="",
        metadata={"department": "hr"},
    )
    vector_store = StaticVectorStore([chunk])
    service = RetrievalService(
        repo=RejectingDocumentRepository(),
        vector_store=vector_store,
        runtime_retrieval=RuntimeRetrievalService(tmp_path / "runtime_retrieval.json"),
        embeddings=DisabledEmbeddings(),
    )

    results = service.search("leave requests")

    assert [item.chunk_id for item in results] == [chunk.id]
    assert vector_store.calls
    assert vector_store.calls[0]["query"] == "leave requests"


def test_retrieval_debug_reports_scores_variants_and_filter_reasons(tmp_path: Path) -> None:
    from app.services.retrieval import RetrievalService

    chunks = [
        Chunk(
            id="chunk-debug-primary",
            document_id="doc-debug",
            document_title="Leave Policy",
            text="Leave approval requires manager approval before annual leave starts.",
            chunk_index=0,
            tokens=["leave", "approval", "requires", "manager", "approval", "annual", "leave"],
            embedding=[],
            embedding_version="",
            metadata={},
        ),
        Chunk(
            id="chunk-debug-secondary",
            document_id="doc-debug",
            document_title="Leave Policy",
            text="Employees submit leave requests one business day in advance.",
            chunk_index=1,
            tokens=["employees", "submit", "leave", "requests", "business", "day", "advance"],
            embedding=[],
            embedding_version="",
            metadata={},
        ),
        Chunk(
            id="chunk-debug-duplicate",
            document_id="doc-debug",
            document_title="Leave Policy",
            text="Leave approval requires manager approval before annual leave starts.",
            chunk_index=2,
            tokens=["leave", "approval", "requires", "manager", "approval", "annual", "leave"],
            embedding=[],
            embedding_version="",
            metadata={},
        ),
        Chunk(
            id="chunk-debug-low",
            document_id="doc-security",
            document_title="Badge Policy",
            text="Security badges must be visible in the office lobby.",
            chunk_index=0,
            tokens=["security", "badges", "visible", "office", "lobby"],
            embedding=[],
            embedding_version="",
            metadata={},
        ),
    ]
    service = RetrievalService(
        repo=RejectingDocumentRepository(),
        vector_store=StaticVectorStore(chunks),
        runtime_retrieval=RuntimeRetrievalService(tmp_path / "runtime_retrieval.json"),
        embeddings=DisabledEmbeddings(),
    )

    debug = service.debug_search(
        "leave approval",
        query_variants=["leave request approval", "leave approval"],
        top_k=1,
        candidate_k=4,
        keyword_weight=1.0,
        semantic_weight=0.0,
        rerank_weight=0.5,
        min_score=0.2,
    )

    assert [item["label"] for item in debug["query_variants"]] == ["primary", "expand_1"]
    assert debug["settings"]["top_k"] == 1
    assert debug["settings"]["candidate_k"] == 4
    assert [item["chunk_id"] for item in debug["results"]] == ["chunk-debug-primary"]
    assert any(item["filter_reason"] == "selected" for item in debug["candidates"])
    assert any(item["filter_reason"] == "duplicate" for item in debug["candidates"])
    assert any(item["filter_reason"] == "below_min_score" for item in debug["candidates"])
    assert all(
        {"keyword_score", "semantic_score", "rerank_score", "matched_query", "query_variant"} <= set(item)
        for item in debug["candidates"]
    )


def test_retrieval_debug_handles_empty_query(tmp_path: Path) -> None:
    from app.services.retrieval import RetrievalService

    service = RetrievalService(
        repo=RejectingDocumentRepository(),
        vector_store=StaticVectorStore([]),
        runtime_retrieval=RuntimeRetrievalService(tmp_path / "runtime_retrieval.json"),
        embeddings=DisabledEmbeddings(),
    )

    debug = service.debug_search("   ")

    assert debug["query_variants"] == []
    assert debug["candidates"] == []
    assert debug["results"] == []


def test_local_vector_store_delegates_to_existing_chunk_storage() -> None:
    from app.vector_store import LocalVectorStore

    now = utc_now()
    repo = DocumentRepository()
    document = repo.upsert_document(
        Document(
            id="doc-local-vector",
            title="Local Vector",
            content="local vector fallback",
            created_at=now,
            updated_at=now,
            indexed_at=now,
            index_state=DocumentIndexState.indexed,
        )
    )
    chunk = Chunk(
        id="chunk-local-vector",
        document_id=document.id,
        document_title=document.title,
        text=document.content,
        chunk_index=0,
        tokens=["local", "vector", "fallback"],
        embedding=[0.1, 0.2],
        embedding_version="test-v1",
        metadata={},
    )
    vector_store = LocalVectorStore(repo)

    assert vector_store.replace_document_chunks(document.id, [chunk]) == 1
    assert vector_store.count_chunks_for_document(document.id) == 1
    assert vector_store.count_embedded_chunks_for_document(document.id) == 1
    assert vector_store.list_chunks_for_document(document.id)[0].id == chunk.id
    assert vector_store.search_candidates("local", [], limit=1)[0].id == chunk.id
    assert vector_store.delete_document(document.id) is True
    assert vector_store.count_chunks_for_document(document.id) == 0


def test_settings_default_to_local_vector_store_provider() -> None:
    from app.config import settings

    assert settings.vector_store_provider == "local"
    assert settings.milvus_collection == "aegis_chunks"


def test_container_uses_milvus_vector_store_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings
    from app.deps import Container
    from app.vector_store import MilvusVectorStore

    class FakeDataType:
        VARCHAR = "varchar"

    class FakeMilvusClient:
        instances: list["FakeMilvusClient"] = []

        def __init__(self, *, uri: str, token: str | None = None) -> None:
            self.uri = uri
            self.token = token
            self.created_collections: list[dict[str, object]] = []
            FakeMilvusClient.instances.append(self)

        def has_collection(self, collection_name: str) -> bool:
            return False

        def create_collection(self, **kwargs: object) -> None:
            self.created_collections.append(kwargs)

    monkeypatch.setitem(
        __import__("sys").modules,
        "pymilvus",
        SimpleNamespace(MilvusClient=FakeMilvusClient, DataType=FakeDataType),
    )

    original = {
        "vector_store_provider": settings.vector_store_provider,
        "milvus_uri": settings.milvus_uri,
        "milvus_token": settings.milvus_token,
        "milvus_collection": settings.milvus_collection,
        "embedding_dimensions": settings.embedding_dimensions,
    }
    try:
        settings.vector_store_provider = "milvus"
        settings.milvus_uri = "http://milvus.example:19530"
        settings.milvus_token = "token"
        settings.milvus_collection = "test_chunks"
        settings.embedding_dimensions = 3

        container = Container()

        assert isinstance(container.vector_store, MilvusVectorStore)
        assert FakeMilvusClient.instances[0].uri == "http://milvus.example:19530"
        assert FakeMilvusClient.instances[0].token == "token"
        assert FakeMilvusClient.instances[0].created_collections[0]["collection_name"] == "test_chunks"
        assert FakeMilvusClient.instances[0].created_collections[0]["dimension"] == 3
    finally:
        for key, value in original.items():
            setattr(settings, key, value)


def test_milvus_vector_store_reports_missing_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.vector_store import MilvusVectorStore

    monkeypatch.setitem(__import__("sys").modules, "pymilvus", None)

    with pytest.raises(RuntimeError, match="pymilvus.*pip install"):
        MilvusVectorStore(
            uri="http://localhost:19530",
            token="",
            collection="aegis_chunks",
            dimension=3,
        )


def test_retrieval_requires_vector_store_argument(tmp_path: Path) -> None:
    from app.services.retrieval import RetrievalService

    with pytest.raises(TypeError):
        RetrievalService(  # type: ignore[call-arg]
            RejectingDocumentRepository(),
            RuntimeRetrievalService(tmp_path / "runtime_retrieval.json"),
            DisabledEmbeddings(),
        )
