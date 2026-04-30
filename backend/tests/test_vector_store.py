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
    def __init__(self, chunks: list[Chunk], search_chunks: list[Chunk] | None = None) -> None:
        self.chunks = chunks
        self.search_chunks = search_chunks
        self.calls: list[dict[str, object]] = []

    def search_candidates(self, query: str, query_embedding: list[float], limit: int) -> list[Chunk]:
        self.calls.append({"query": query, "query_embedding": query_embedding, "limit": limit})
        return self.search_chunks if self.search_chunks is not None else self.chunks

    def list_chunks(self) -> list[Chunk]:
        return self.chunks

    def list_chunks_for_document(self, document_id: str) -> list[Chunk]:
        return [chunk for chunk in self.chunks if chunk.document_id == document_id]


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


def test_retrieval_adds_keyword_candidates_when_vector_search_misses_exact_section(tmp_path: Path) -> None:
    from app.services.retrieval import RetrievalService

    relevant = Chunk(
        id="chunk-admission-conditions",
        document_id="doc-admission",
        document_title="Graduate Admission Guide",
        text=(
            "一、报考条件。报名参加全国硕士研究生招生考试的人员，须符合下列条件："
            "1. 中华人民共和国公民。2. 拥护中国共产党的领导。"
            "3. 身体健康状况符合体检要求。"
        ),
        chunk_index=0,
        tokens=["一", "报", "考", "条", "件", "报考", "条件", "硕士", "研究生"],
        embedding=[],
        embedding_version="",
        metadata={},
    )
    vector_only = Chunk(
        id="chunk-vector-nearby",
        document_id="doc-admission",
        document_title="Graduate Admission Guide",
        text="中山大学研究生招生办公室联系方式和咨询电话。",
        chunk_index=5,
        tokens=["中山大学", "研究生", "招生", "办公室"],
        embedding=[],
        embedding_version="",
        metadata={},
    )
    service = RetrievalService(
        repo=RejectingDocumentRepository(),
        vector_store=StaticVectorStore([relevant, vector_only], search_chunks=[vector_only]),
        runtime_retrieval=RuntimeRetrievalService(tmp_path / "runtime_retrieval.json"),
        embeddings=DisabledEmbeddings(),
    )

    results = service.search("报考中山大学研究生条件", top_k=1)

    assert [item.chunk_id for item in results] == [relevant.id]


def test_retrieval_expands_adjacent_chunks_for_section_heading_hits(tmp_path: Path) -> None:
    from app.services.retrieval import RetrievalService

    heading = Chunk(
        id="chunk-conditions-heading",
        document_id="doc-admission",
        document_title="Graduate Admission Guide",
        text="一、报考条件。报名参加全国硕士研究生招生考试的人员，须符合下列条件。",
        chunk_index=0,
        tokens=["一", "报", "考", "条", "件", "报考", "条件"],
        embedding=[],
        embedding_version="",
        metadata={},
    )
    adjacent = Chunk(
        id="chunk-conditions-medical",
        document_id="doc-admission",
        document_title="Graduate Admission Guide",
        text="报考医学临床学科学术学位的人员，只接受授医学学位的毕业生报考。",
        chunk_index=1,
        tokens=["医学", "临床", "学术", "学位", "毕业生"],
        embedding=[],
        embedding_version="",
        metadata={},
    )
    service = RetrievalService(
        repo=RejectingDocumentRepository(),
        vector_store=StaticVectorStore([heading, adjacent], search_chunks=[heading]),
        runtime_retrieval=RuntimeRetrievalService(tmp_path / "runtime_retrieval.json"),
        embeddings=DisabledEmbeddings(),
    )

    results = service.search("报考条件", top_k=2)

    assert [item.chunk_id for item in results] == [heading.id, adjacent.id]


def test_retrieval_expands_same_section_children_for_parent_heading_hits(tmp_path: Path) -> None:
    from app.services.retrieval import RetrievalService

    parent = Chunk(
        id="chunk-conditions-parent",
        document_id="doc-admission",
        document_title="Graduate Admission Guide",
        text="一、报考条件",
        chunk_index=0,
        tokens=["报", "考", "条", "件", "报考", "条件"],
        embedding=[],
        embedding_version="",
        metadata={
            "section_path": "报考条件",
            "section_title": "报考条件",
            "section_level": 1,
            "section_index": 1,
        },
    )
    basic = Chunk(
        id="chunk-conditions-basic",
        document_id="doc-admission",
        document_title="Graduate Admission Guide",
        text="报考条件 > 报名参加全国硕士研究生招生考试的人员。1. 中华人民共和国公民。",
        chunk_index=8,
        tokens=["报考", "条件", "中华人民共和国", "公民"],
        embedding=[],
        embedding_version="",
        metadata={
            "section_path": "报考条件 > 报名参加全国硕士研究生招生考试的人员",
            "section_title": "报名参加全国硕士研究生招生考试的人员",
            "section_level": 2,
            "section_index": 2,
        },
    )
    medical = Chunk(
        id="chunk-conditions-medical",
        document_id="doc-admission",
        document_title="Graduate Admission Guide",
        text="报考条件 > 报考医学临床学科学术学位的人员。只接受授医学学位的毕业生报考。",
        chunk_index=12,
        tokens=["报考", "条件", "医学", "临床", "学术", "学位"],
        embedding=[],
        embedding_version="",
        metadata={
            "section_path": "报考条件 > 报考医学临床学科学术学位的人员",
            "section_title": "报考医学临床学科学术学位的人员",
            "section_level": 2,
            "section_index": 3,
        },
    )
    unrelated = Chunk(
        id="chunk-registration",
        document_id="doc-admission",
        document_title="Graduate Admission Guide",
        text="二、报名。考生应完成网上报名。",
        chunk_index=20,
        tokens=["报名", "网上"],
        embedding=[],
        embedding_version="",
        metadata={
            "section_path": "报名",
            "section_title": "报名",
            "section_level": 1,
            "section_index": 4,
        },
    )
    service = RetrievalService(
        repo=RejectingDocumentRepository(),
        vector_store=StaticVectorStore([parent, basic, medical, unrelated], search_chunks=[parent]),
        runtime_retrieval=RuntimeRetrievalService(tmp_path / "runtime_retrieval.json"),
        embeddings=DisabledEmbeddings(),
    )

    results = service.search("报考条件", top_k=3)

    assert [item.chunk_id for item in results] == [parent.id, basic.id, medical.id]


def test_retrieval_recalls_multiple_admission_condition_structure_blocks(tmp_path: Path) -> None:
    from app.services.retrieval import RetrievalService
    from app.services.text import split_into_structured_chunks, tokenize

    text = """
中山大学2026年考试招收硕士研究生招生简章

一、报考条件
（一）报名参加全国硕士研究生招生考试的人员，须符合下列条件：
1. 中华人民共和国公民。
2. 拥护中国共产党的领导，遵纪守法，品德良好。
3. 身体健康状况符合国家和中山大学规定的体检要求。

（二）报考医学临床学科学术学位的人员，须符合医学培养要求。
1. 只接受授医学学位的毕业生报考。

（三）报考法律硕士（非法学）专业学位的人员，报考前所学专业为非法学专业。

（四）报考工商管理、公共管理、旅游管理等管理类专业学位的人员，须符合工作年限要求。

（五）报名参加单独考试的人员，须经所在单位同意并具有相应工作经历。

二、报名
考生应按教育部和学校要求完成网上报名。
"""
    structured_chunks = split_into_structured_chunks(text)
    chunks = [
        Chunk(
            id=f"chunk-{index}",
            document_id="doc-admission",
            document_title="中山大学2026年考试招收硕士研究生招生简章",
            text=item.text,
            chunk_index=index,
            tokens=tokenize(item.text),
            embedding=[],
            embedding_version="",
            metadata=item.metadata,
        )
        for index, item in enumerate(structured_chunks)
    ]
    parent = next(chunk for chunk in chunks if chunk.metadata.get("section_path") == "报考条件")
    service = RetrievalService(
        repo=RejectingDocumentRepository(),
        vector_store=StaticVectorStore(chunks, search_chunks=[parent]),
        runtime_retrieval=RuntimeRetrievalService(tmp_path / "runtime_retrieval.json"),
        embeddings=DisabledEmbeddings(),
    )

    results = service.search("报考条件", top_k=6)
    section_paths = [item.metadata.get("section_path", "") for item in results]

    assert any("报名参加全国硕士研究生招生考试的人员" in path for path in section_paths)
    assert any("医学临床学科学术学位" in path for path in section_paths)
    assert any("法律硕士（非法学）" in path for path in section_paths)
    assert any("工商管理、公共管理、旅游管理" in path for path in section_paths)
    assert any("单独考试" in path for path in section_paths)


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
