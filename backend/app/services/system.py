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
        retrieval = self.runtime_retrieval.get_settings()
        conversation_count = (
            len(self.conversations.list())
            if user.role == UserRole.admin
            else len(self.conversations.list_for_user(user.id))
        )
        task_count = len(self.tasks.list()) if user.role == UserRole.admin else len(self.tasks.list_for_user(user.id))
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
            embedded_chunks=sum(1 for chunk in self.documents.list_chunks() if chunk.embedding),
            api_key_configured=bool(runtime["api_key_configured"]),
            embedding_api_key_configured=bool(embedding_runtime["api_key_configured"]),
        )
