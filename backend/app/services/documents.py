from __future__ import annotations

from queue import Queue
from threading import Lock, Thread

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
from ..vector_store import VectorStore
from .embeddings import EmbeddingService
from .text import normalize_text, split_into_structured_chunks, tokenize


class DocumentService:
    def __init__(
        self,
        repo: DocumentRepository,
        task_repo: DocumentTaskRepository,
        vector_store: VectorStore,
        embeddings: EmbeddingService,
    ) -> None:
        self.repo = repo
        self.task_repo = task_repo
        self.vector_store = vector_store
        self.embeddings = embeddings
        self._task_queue: Queue[str] = Queue()
        self._active_task_ids: set[str] = set()
        self._active_lock = Lock()
        self._worker = Thread(target=self._worker_loop, name="document-index-worker", daemon=True)
        self._worker.start()

    def get_current_embedding_version(self) -> str:
        return self.embeddings.get_version()

    def get_active_task_count(self) -> int:
        with self._active_lock:
            return len(self._active_task_ids)

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
        document = self.create_document(
            title=title,
            content=content,
            source_type=source_type,
            department=department,
            version=version,
            tags=tags,
        )
        task = self.task_repo.save(
            DocumentTask(
                user_id=user_id,
                document_id=document.id,
                document_title=document.title,
                kind=DocumentTaskKind.upload,
                status=DocumentTaskStatus.pending,
                progress=5,
                message="已进入索引队列，等待后台处理",
                queued_at=utc_now(),
            )
        )
        self._mark_document_queued(document, task)
        self._enqueue_task(task)
        return document, task, 0

    def list_documents(self) -> list[Document]:
        return self.repo.list_documents()

    def get_document(self, document_id: str) -> Document | None:
        return self.repo.get_document(document_id)

    def delete_document(self, document_id: str) -> bool:
        self.vector_store.delete_document(document_id)
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
                progress=5,
                message="已进入索引队列，等待后台处理",
                queued_at=utc_now(),
            )
        )
        self._mark_document_queued(document, task)
        self._enqueue_task(task)
        return document, task, 0

    def bulk_reindex(self, *, user_id: str, mode: str) -> dict[str, object]:
        normalized_mode = mode.strip().lower() or "missing_embeddings"
        if normalized_mode not in {"all", "missing_embeddings", "outdated_embeddings"}:
            raise ValueError("mode 仅支持 all、missing_embeddings 或 outdated_embeddings")

        documents = self.repo.list_documents()
        chunk_stats = self.vector_store.get_chunk_stats()
        selected: list[Document] = []
        skipped_documents = 0
        current_embedding_version = self.get_current_embedding_version()
        for document in documents:
            stats = chunk_stats.get(document.id, {"chunk_count": 0, "embedded_chunk_count": 0})
            needs_reindex = self.document_requires_reindex(
                document,
                chunk_count=int(stats["chunk_count"]),
                embedded_chunk_count=int(stats["embedded_chunk_count"]),
                current_embedding_version=current_embedding_version,
            )
            if normalized_mode == "all":
                selected.append(document)
            elif normalized_mode == "missing_embeddings":
                if needs_reindex:
                    selected.append(document)
                else:
                    skipped_documents += 1
            elif self._embedding_version_stale(document, current_embedding_version):
                selected.append(document)
            else:
                skipped_documents += 1

        failures: list[dict[str, str]] = []
        queued_documents = 0
        for document in selected:
            try:
                self.reindex_document(document.id, user_id)
            except Exception as exc:
                failures.append(
                    {
                        "document_id": document.id,
                        "title": document.title,
                        "error": str(exc),
                    }
                )
                continue
            queued_documents += 1

        return {
            "mode": normalized_mode,
            "requested_documents": len(selected),
            "queued_documents": queued_documents,
            "skipped_documents": skipped_documents,
            "active_tasks": self.get_active_task_count(),
            "failed_documents": failures,
        }

    def index_document(self, document_id: str) -> int:
        document = self.repo.get_document(document_id)
        if document is None:
            raise KeyError(document_id)
        chunks = self._build_chunks(document)
        now = utc_now()
        document.indexed_at = now
        document.updated_at = now
        document.index_state = DocumentIndexState.indexed
        document.embedding_version = self._resolved_document_embedding_version(chunks)
        document.last_index_error = ""
        self.repo.upsert_document(document)
        return self.vector_store.replace_document_chunks(document.id, chunks)

    def document_requires_reindex(
        self,
        document: Document,
        *,
        chunk_count: int,
        embedded_chunk_count: int,
        current_embedding_version: str,
    ) -> bool:
        if document.index_state != DocumentIndexState.indexed:
            return True
        if chunk_count <= 0:
            return True
        if self.embeddings.is_enabled() and embedded_chunk_count < chunk_count:
            return True
        if self._embedding_version_stale(document, current_embedding_version):
            return True
        return False

    def _embedding_version_stale(self, document: Document, current_embedding_version: str) -> bool:
        if not self.embeddings.is_enabled():
            return False
        if not current_embedding_version or current_embedding_version == "disabled":
            return False
        return document.embedding_version != current_embedding_version

    def _enqueue_task(self, task: DocumentTask) -> None:
        self._task_queue.put(task.id)

    def _worker_loop(self) -> None:
        while True:
            task_id = self._task_queue.get()
            try:
                self._process_task(task_id)
            finally:
                self._task_queue.task_done()

    def _process_task(self, task_id: str) -> None:
        task = self.task_repo.get(task_id)
        if task is None:
            return
        if not task.document_id:
            task.status = DocumentTaskStatus.failed
            task.message = "处理失败"
            task.error = "任务缺少 document_id"
            task.completed_at = utc_now()
            self.task_repo.save(task)
            return

        document = self.repo.get_document(task.document_id)
        if document is None:
            task.status = DocumentTaskStatus.failed
            task.message = "处理失败"
            task.error = "文档不存在"
            task.completed_at = utc_now()
            self.task_repo.save(task)
            return

        with self._active_lock:
            self._active_task_ids.add(task.id)
        try:
            self._index_document(document, task)
        finally:
            with self._active_lock:
                self._active_task_ids.discard(task.id)

    def _index_document(self, document: Document, task: DocumentTask) -> int:
        self._mark_document_indexing(document, task)
        self._update_task(
            task,
            status=DocumentTaskStatus.running,
            progress=18,
            message="后台任务已启动，正在准备索引",
            started_at=utc_now(),
        )
        self._update_task(task, progress=42, message="正在切分文档片段")
        try:
            chunks = self._build_chunks(document)
            self._update_task(task, progress=78, message="正在写入索引和向量")
            chunks_created = self.vector_store.replace_document_chunks(document.id, chunks)
        except Exception as exc:
            self._mark_document_failed(document, task, str(exc))
            raise

        now = utc_now()
        document.indexed_at = now
        document.updated_at = now
        document.index_state = DocumentIndexState.indexed
        document.embedding_version = self._resolved_document_embedding_version(chunks)
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

    def _mark_document_queued(self, document: Document, task: DocumentTask) -> None:
        now = utc_now()
        document.updated_at = now
        document.index_state = DocumentIndexState.indexing
        document.last_index_error = ""
        document.last_task_id = task.id
        if task.kind == DocumentTaskKind.upload:
            document.last_upload_task_id = task.id
        self.repo.upsert_document(document)

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
        started_at=None,
    ) -> DocumentTask:
        task.updated_at = utc_now()
        if status is not None:
            task.status = status
        if progress is not None:
            task.progress = max(0, min(progress, 100))
        if message is not None:
            task.message = message
        if started_at is not None and task.started_at is None:
            task.started_at = started_at
        return self.task_repo.save(task)

    def _build_chunks(self, document: Document) -> list[Chunk]:
        structured_chunks = list(split_into_structured_chunks(document.content))
        chunk_texts = [chunk.text for chunk in structured_chunks]
        vectors = self.embeddings.embed_texts(chunk_texts) if self.embeddings.is_enabled() else []
        embedding_version = self.embeddings.get_version() if vectors else ""
        return [
            Chunk(
                document_id=document.id,
                document_title=document.title,
                text=chunk_text,
                chunk_index=index,
                tokens=tokenize(chunk_text),
                embedding=vectors[index] if index < len(vectors) else [],
                embedding_version=embedding_version if index < len(vectors) else "",
                metadata={
                    "department": document.department,
                    "version": document.version,
                    "tags": document.tags,
                    **structured_chunks[index].metadata,
                },
            )
            for index, chunk_text in enumerate(chunk_texts)
        ]

    def _resolved_document_embedding_version(self, chunks: list[Chunk]) -> str:
        for chunk in chunks:
            if chunk.embedding_version:
                return chunk.embedding_version
        return self.embeddings.get_version() if not self.embeddings.is_enabled() else ""
