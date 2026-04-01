from __future__ import annotations

from ..models import (
    Chunk,
    Document,
    DocumentIndexState,
    DocumentTask,
    DocumentTaskKind,
    DocumentTaskStatus,
    utc_now,
)
from ..repositories import DocumentRepository, DocumentTaskRepository
from .embeddings import EmbeddingService
from .text import normalize_text, split_into_chunks, tokenize


class DocumentService:
    def __init__(
        self,
        repo: DocumentRepository,
        task_repo: DocumentTaskRepository,
        embeddings: EmbeddingService,
    ) -> None:
        self.repo = repo
        self.task_repo = task_repo
        self.embeddings = embeddings

    def create_document(
        self,
        *,
        title: str,
        content: str,
        source_type: str,
        department: str,
        version: str,
        tags: list[str],
    ) -> Document:
        now = utc_now()
        document = Document(
            title=title,
            content=normalize_text(content),
            source_type=source_type,
            department=department,
            version=version,
            tags=tags,
            created_at=now,
            updated_at=now,
            index_state=DocumentIndexState.pending,
        )
        return self.repo.upsert_document(document)

    def import_document(
        self,
        *,
        user_id: str,
        title: str,
        content: str,
        source_type: str,
        department: str,
        version: str,
        tags: list[str],
    ) -> tuple[Document, DocumentTask, int]:
        task = self.task_repo.save(
            DocumentTask(
                user_id=user_id,
                document_title=title,
                kind=DocumentTaskKind.upload,
                status=DocumentTaskStatus.pending,
                message="等待写入文档",
            )
        )
        self._update_task(task, status=DocumentTaskStatus.running, progress=15, message="正在创建文档记录")
        document = self.create_document(
            title=title,
            content=content,
            source_type=source_type,
            department=department,
            version=version,
            tags=tags,
        )
        task.document_id = document.id
        task.document_title = document.title
        self.task_repo.save(task)
        chunks_created = self._index_document(document, task)
        return document, task, chunks_created

    def list_documents(self) -> list[Document]:
        return self.repo.list_documents()

    def get_document(self, document_id: str) -> Document | None:
        return self.repo.get_document(document_id)

    def delete_document(self, document_id: str) -> bool:
        return self.repo.delete_document(document_id)

    def get_document_task(self, task_id: str) -> DocumentTask | None:
        return self.task_repo.get(task_id)

    def list_document_tasks(self, document_id: str, limit: int | None = None) -> list[DocumentTask]:
        return self.task_repo.list_for_document(document_id, limit=limit)

    def reindex_document(self, document_id: str, user_id: str) -> tuple[Document, DocumentTask, int]:
        document = self.repo.get_document(document_id)
        if document is None:
            raise KeyError(document_id)
        task = self.task_repo.save(
            DocumentTask(
                user_id=user_id,
                document_id=document.id,
                document_title=document.title,
                kind=DocumentTaskKind.reindex,
                status=DocumentTaskStatus.pending,
                message="等待重建索引",
            )
        )
        chunks_created = self._index_document(document, task)
        return document, task, chunks_created

    def index_document(self, document_id: str) -> int:
        document = self.repo.get_document(document_id)
        if document is None:
            raise KeyError(document_id)
        chunks = self._build_chunks(document)
        now = utc_now()
        document.indexed_at = now
        document.updated_at = now
        document.index_state = DocumentIndexState.indexed
        document.last_index_error = ""
        self.repo.upsert_document(document)
        return self.repo.replace_chunks(document.id, chunks)

    def _index_document(self, document: Document, task: DocumentTask) -> int:
        self._mark_document_indexing(document, task)
        self._update_task(task, status=DocumentTaskStatus.running, progress=35, message="正在切分文档片段")
        try:
            chunks = self._build_chunks(document)
            self._update_task(task, progress=78, message="正在写入索引")
            chunks_created = self.repo.replace_chunks(document.id, chunks)
        except Exception as exc:
            self._mark_document_failed(document, task, str(exc))
            raise

        now = utc_now()
        document.indexed_at = now
        document.updated_at = now
        document.index_state = DocumentIndexState.indexed
        document.last_index_error = ""
        document.last_task_id = task.id
        if task.kind == DocumentTaskKind.upload:
            document.last_upload_task_id = task.id
        self.repo.upsert_document(document)

        task.status = DocumentTaskStatus.succeeded
        task.progress = 100
        task.message = "处理完成"
        task.error = ""
        task.chunks_created = chunks_created
        task.updated_at = now
        task.completed_at = now
        self.task_repo.save(task)
        return chunks_created

    def _mark_document_indexing(self, document: Document, task: DocumentTask) -> None:
        now = utc_now()
        document.updated_at = now
        document.index_state = DocumentIndexState.indexing
        document.last_index_error = ""
        document.last_task_id = task.id
        if task.kind == DocumentTaskKind.upload:
            document.last_upload_task_id = task.id
        self.repo.upsert_document(document)

    def _mark_document_failed(self, document: Document, task: DocumentTask, error: str) -> None:
        now = utc_now()
        document.updated_at = now
        document.index_state = DocumentIndexState.failed
        document.last_index_error = error
        document.last_task_id = task.id
        if task.kind == DocumentTaskKind.upload:
            document.last_upload_task_id = task.id
        self.repo.upsert_document(document)

        task.status = DocumentTaskStatus.failed
        task.message = "处理失败"
        task.error = error
        task.updated_at = now
        task.completed_at = now
        self.task_repo.save(task)

    def _update_task(
        self,
        task: DocumentTask,
        *,
        status: DocumentTaskStatus | None = None,
        progress: int | None = None,
        message: str | None = None,
    ) -> DocumentTask:
        task.updated_at = utc_now()
        if status is not None:
            task.status = status
        if progress is not None:
            task.progress = max(0, min(progress, 100))
        if message is not None:
            task.message = message
        return self.task_repo.save(task)

    def _build_chunks(self, document: Document) -> list[Chunk]:
        chunk_texts = list(split_into_chunks(document.content))
        vectors = self.embeddings.embed_texts(chunk_texts) if self.embeddings.is_enabled() else []
        return [
            Chunk(
                document_id=document.id,
                document_title=document.title,
                text=chunk_text,
                chunk_index=index,
                tokens=tokenize(chunk_text),
                embedding=vectors[index] if index < len(vectors) else [],
                metadata={
                    "department": document.department,
                    "version": document.version,
                    "tags": document.tags,
                },
            )
            for index, chunk_text in enumerate(chunk_texts)
        ]
