from __future__ import annotations

from pathlib import Path

from app.models import Chunk, Document, DocumentIndexState, RetrievalResult, utc_now
from app.repositories import DocumentRepository
from app.services.documents import DocumentService
from app.services.runtime_retrieval import RuntimeRetrievalService


class DisabledEmbeddings:
    def is_enabled(self) -> bool:
        return False

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise AssertionError("disabled embeddings should not embed")

    def get_version(self) -> str:
        return "disabled"


class MemoryTaskRepo:
    pass


class MemoryVectorStore:
    def __init__(self, repo: DocumentRepository) -> None:
        self.repo = repo

    def replace_document_chunks(self, document_id: str, chunks: list[Chunk]) -> int:
        return self.repo.replace_chunks(document_id, chunks)

    def list_chunks_for_document(self, document_id: str) -> list[Chunk]:
        return self.repo.list_chunks_for_document(document_id)


def test_document_index_persists_parent_child_chunk_metadata(tmp_path: Path) -> None:
    repo = DocumentRepository()
    vector_store = MemoryVectorStore(repo)
    service = DocumentService(
        repo=repo,
        task_repo=MemoryTaskRepo(),  # type: ignore[arg-type]
        vector_store=vector_store,  # type: ignore[arg-type]
        embeddings=DisabledEmbeddings(),  # type: ignore[arg-type]
        start_worker=False,
    )
    document = repo.upsert_document(
        Document(
            title="欧洲 DDP 渠道清关资料表",
            content="""
# 欧洲 DDP 渠道清关资料表
## 德国
### 带电产品
德国 DDP 带电产品需要 MSDS、UN38.3、运输鉴定书。
### 纯电池
德国 DDP 纯电池不接。
""",
            source_type="text",
            department="logistics",
            version="v1",
            tags=["跨境物流"],
            created_at=utc_now(),
            updated_at=utc_now(),
            index_state=DocumentIndexState.pending,
        )
    )

    service.index_document(document.id)
    chunks = vector_store.list_chunks_for_document(document.id)

    root = next(chunk for chunk in chunks if chunk.metadata["section_path"] == "欧洲 DDP 渠道清关资料表")
    germany = next(chunk for chunk in chunks if chunk.metadata["section_path"] == "欧洲 DDP 渠道清关资料表 > 德国")
    battery = next(chunk for chunk in chunks if chunk.metadata["section_path"].endswith("带电产品"))

    assert root.metadata["chunk_role"] == "parent"
    assert germany.metadata["parent_chunk_id"] == root.id
    assert battery.metadata["parent_chunk_id"] == germany.id
    assert battery.id in germany.metadata["child_chunk_ids"]
    assert germany.id in root.metadata["child_chunk_ids"]


def test_retrieval_same_section_expansion_can_use_parent_child_metadata(tmp_path: Path) -> None:
    from app.services.retrieval import RetrievalService

    parent = Chunk(
        id="chunk-parent",
        document_id="doc-1",
        document_title="欧洲 DDP 渠道清关资料表",
        text="德国 DDP",
        chunk_index=0,
        tokens=["德国", "ddp"],
        metadata={
            "section_path": "欧洲 DDP 渠道清关资料表 > 德国",
            "child_chunk_ids": ["chunk-child"],
        },
    )
    child = Chunk(
        id="chunk-child",
        document_id="doc-1",
        document_title="欧洲 DDP 渠道清关资料表",
        text="带电产品需要 MSDS。",
        chunk_index=1,
        tokens=["带电", "msds"],
        metadata={
            "section_path": "欧洲 DDP 渠道清关资料表 > 德国 > 带电产品",
            "parent_chunk_id": "chunk-parent",
        },
    )
    repo = DocumentRepository()
    vector_store = MemoryVectorStore(repo)
    vector_store.replace_document_chunks("doc-1", [parent, child])
    service = RetrievalService(
        repo=repo,
        vector_store=vector_store,  # type: ignore[arg-type]
        runtime_retrieval=RuntimeRetrievalService(tmp_path / "runtime.json"),
        embeddings=DisabledEmbeddings(),  # type: ignore[arg-type]
    )

    expanded = service._same_section_chunk_results(
        RetrievalResult(
            chunk_id=parent.id,
            document_id=parent.document_id,
            document_title=parent.document_title,
            text=parent.text,
            score=1.0,
            source=f"{parent.document_title}#chunk-{parent.chunk_index}",
            metadata=parent.metadata,
        )
    )

    assert any(item.chunk_id == "chunk-child" for item in expanded)
