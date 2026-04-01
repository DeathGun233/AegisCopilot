from __future__ import annotations

from ..config import settings
from ..models import SystemStats, User, UserRole
from ..repositories import ConversationRepository, DocumentRepository, TaskRepository
from .embeddings import EmbeddingService
from .runtime_models import RuntimeModelService
from .runtime_retrieval import RuntimeRetrievalService


class SystemService:
    def __init__(
        self,
        conversations: ConversationRepository,
        documents: DocumentRepository,
        tasks: TaskRepository,
        runtime_models: RuntimeModelService,
        runtime_retrieval: RuntimeRetrievalService,
        embeddings: EmbeddingService,
    ) -> None:
        self.conversations = conversations
        self.documents = documents
        self.tasks = tasks
        self.runtime_models = runtime_models
        self.runtime_retrieval = runtime_retrieval
        self.embeddings = embeddings

    def get_stats(self, user: User) -> SystemStats:
        runtime = self.runtime_models.get_runtime()
        embedding_runtime = self.embeddings.get_runtime()
        current_embedding_version = self.embeddings.get_version()
        retrieval = self.runtime_retrieval.get_settings()
        chunk_stats = self.documents.get_chunk_stats()
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
            indexed_chunks=len(self.documents.list_chunks()),
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
            embedded_chunks=sum(1 for chunk in self.documents.list_chunks() if chunk.embedding),
            pending_embedding_documents=pending_embedding_documents,
            stale_embedding_documents=stale_embedding_documents,
            api_key_configured=bool(runtime["api_key_configured"]),
            embedding_api_key_configured=bool(embedding_runtime["api_key_configured"]),
        )
