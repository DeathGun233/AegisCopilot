from __future__ import annotations

from ..config import settings
from ..models import SystemStats, User, UserRole
from ..repositories import ConversationRepository, DocumentRepository, TaskRepository
from .runtime_models import RuntimeModelService


class SystemService:
    def __init__(
        self,
        conversations: ConversationRepository,
        documents: DocumentRepository,
        tasks: TaskRepository,
        runtime_models: RuntimeModelService,
    ) -> None:
        self.conversations = conversations
        self.documents = documents
        self.tasks = tasks
        self.runtime_models = runtime_models

    def get_stats(self, user: User) -> SystemStats:
        runtime = self.runtime_models.get_runtime()
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
            retrieval_top_k=settings.default_retrieval_top_k,
            grounding_threshold=settings.min_grounding_score,
            llm_provider=str(runtime["provider"]),
            llm_model=str(runtime["model"]),
            api_key_configured=bool(runtime["api_key_configured"]),
        )
