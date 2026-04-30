from __future__ import annotations

from collections.abc import Callable

from ..config import settings
from ..models import DocumentTaskStatus, SystemCheck, SystemStats, SystemStatus, User, UserRole
from ..repositories import ConversationRepository, DocumentRepository, DocumentTaskRepository, TaskRepository
from ..vector_store import VectorStore
from .embeddings import EmbeddingService
from .runtime_models import RuntimeModelService
from .runtime_retrieval import RuntimeRetrievalService


class SystemService:
    def __init__(
        self,
        conversations: ConversationRepository,
        documents: DocumentRepository,
        document_tasks: DocumentTaskRepository,
        vector_store: VectorStore,
        tasks: TaskRepository,
        runtime_models: RuntimeModelService,
        runtime_retrieval: RuntimeRetrievalService,
        embeddings: EmbeddingService,
        *,
        database=None,
        active_document_tasks: Callable[[], int] | None = None,
    ) -> None:
        self.conversations = conversations
        self.documents = documents
        self.document_tasks = document_tasks
        self.vector_store = vector_store
        self.tasks = tasks
        self.runtime_models = runtime_models
        self.runtime_retrieval = runtime_retrieval
        self.embeddings = embeddings
        self.database = database
        self.active_document_tasks = active_document_tasks or (lambda: 0)

    def get_stats(self, user: User) -> SystemStats:
        runtime = self.runtime_models.get_runtime()
        embedding_runtime = self.embeddings.get_runtime()
        current_embedding_version = self.embeddings.get_version()
        retrieval = self.runtime_retrieval.get_settings()
        chunk_stats = self.vector_store.get_chunk_stats()
        conversation_count = (
            len(self.conversations.list())
            if user.role == UserRole.admin
            else len(self.conversations.list_for_user(user.id))
        )
        task_count = len(self.tasks.list()) if user.role == UserRole.admin else len(self.tasks.list_for_user(user.id))
        embedded_documents = 0
        pending_embedding_documents = 0
        stale_embedding_documents = 0
        for document in self.documents.list_documents():
            stats = chunk_stats.get(document.id, {"chunk_count": 0, "embedded_chunk_count": 0})
            chunk_count = int(stats["chunk_count"])
            embedded_chunk_count = int(stats["embedded_chunk_count"])
            if embedded_chunk_count > 0:
                embedded_documents += 1
            if chunk_count > 0 and embedded_chunk_count < chunk_count:
                pending_embedding_documents += 1
            if (
                self.embeddings.is_enabled()
                and chunk_count > 0
                and embedded_chunk_count > 0
                and document.embedding_version != current_embedding_version
            ):
                stale_embedding_documents += 1
        return SystemStats(
            documents=len(self.documents.list_documents()),
            indexed_chunks=len(self.vector_store.list_chunks()),
            conversations=conversation_count,
            tasks=task_count,
            retrieval_top_k=retrieval.top_k,
            retrieval_candidate_k=retrieval.candidate_k,
            retrieval_strategy=retrieval.strategy.value,
            grounding_threshold=settings.min_grounding_score,
            llm_provider=str(runtime["provider"]),
            llm_model=str(runtime["model"]),
            embedding_provider=str(embedding_runtime["provider"]),
            embedding_model=str(embedding_runtime["model"]),
            current_embedding_version=current_embedding_version,
            embedding_dimensions=int(embedding_runtime["dimensions"]),
            embedded_documents=embedded_documents,
            embedded_chunks=sum(1 for chunk in self.vector_store.list_chunks() if chunk.embedding),
            pending_embedding_documents=pending_embedding_documents,
            stale_embedding_documents=stale_embedding_documents,
            api_key_configured=bool(runtime["api_key_configured"]),
            embedding_api_key_configured=bool(embedding_runtime["api_key_configured"]),
        )

    def get_status(self) -> SystemStatus:
        providers = {
            "database": self._database_check(),
            "vector": self._vector_check(),
            "embedding": self._embedding_check(),
            "llm": self._llm_check(),
        }
        document_tasks = self._document_task_counts()
        ready = all(check.status != "error" for check in providers.values())
        return SystemStatus(
            status="ready" if ready else "degraded",
            ready=ready,
            providers=providers,
            document_tasks=document_tasks,
        )

    def _database_check(self) -> SystemCheck:
        provider = "json"
        if self.database is not None:
            provider = getattr(self.database, "kind", "sql")
        try:
            if self.database is not None:
                self.database.execute("SELECT 1 AS ok", fetch="one")
            else:
                settings.storage_dir.mkdir(parents=True, exist_ok=True)
            return SystemCheck(
                status="ok",
                provider=provider,
                message=f"{provider} storage is reachable",
                detail={"database_url_configured": bool(settings.database_url)},
            )
        except Exception as exc:
            return SystemCheck(status="error", provider=provider, message=str(exc))

    def _vector_check(self) -> SystemCheck:
        provider = settings.vector_store_provider.strip().lower() or "local"
        detail = {
            "available_providers": ["local", "milvus"],
            "selection_mode": "startup",
            "restart_required_for_changes": True,
            "collection": settings.milvus_collection if provider == "milvus" else "",
            "uri": settings.milvus_uri if provider == "milvus" else "",
        }
        try:
            if provider == "milvus":
                self.vector_store.count_chunks_for_document("__aegis_status_probe__")
            else:
                self.vector_store.get_chunk_stats()
            return SystemCheck(status="ok", provider=provider, message=f"{provider} vector store is reachable", detail=detail)
        except Exception as exc:
            return SystemCheck(status="error", provider=provider, message=str(exc), detail=detail)

    def _embedding_check(self) -> SystemCheck:
        runtime = self.embeddings.get_runtime()
        provider = str(runtime["provider"])
        enabled = bool(runtime["enabled"])
        missing_key = provider == "openai-compatible" and not bool(runtime["api_key_configured"])
        status = "warning" if missing_key else "ok"
        message = "embedding service is enabled" if enabled else "embedding service is disabled or not configured"
        if missing_key:
            message = "embedding provider is configured but API key is missing"
        return SystemCheck(
            status=status,
            provider=provider,
            message=message,
            detail={
                "model": runtime["model"],
                "dimensions": runtime["dimensions"],
                "enabled": enabled,
                "api_key_configured": bool(runtime["api_key_configured"]),
            },
        )

    def _llm_check(self) -> SystemCheck:
        runtime = self.runtime_models.get_runtime()
        provider = str(runtime["provider"])
        missing_key = provider == "openai-compatible" and not bool(runtime["api_key_configured"])
        status = "warning" if missing_key else "ok"
        message = "LLM runtime is configured"
        if provider == "mock":
            message = "mock LLM runtime is active"
        elif missing_key:
            message = "LLM provider is configured but API key is missing"
        return SystemCheck(
            status=status,
            provider=provider,
            message=message,
            detail={
                "model": runtime["model"],
                "base_url_configured": bool(runtime["base_url"]),
                "api_key_configured": bool(runtime["api_key_configured"]),
            },
        )

    def _document_task_counts(self) -> dict[str, int]:
        tasks = self.document_tasks.list()
        return {
            "total": len(tasks),
            "queued": sum(1 for task in tasks if task.status == DocumentTaskStatus.pending),
            "running": sum(1 for task in tasks if task.status == DocumentTaskStatus.running),
            "failed": sum(1 for task in tasks if task.status == DocumentTaskStatus.failed),
            "active": self.active_document_tasks(),
        }
