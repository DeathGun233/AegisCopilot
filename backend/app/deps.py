from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import Header, HTTPException, status

from .config import settings
from .models import User
from .vector_store import LocalVectorStore, MilvusVectorStore, VectorStore
from .repositories import (
    ConversationRepository,
    DocumentRepository,
    DocumentTaskRepository,
    JsonStore,
    SessionRepository,
    TaskRepository,
    UserRepository,
)
from .sql_repositories import (
    SqlConversationRepository,
    SqlDatabase,
    SqlDocumentRepository,
    SqlDocumentTaskRepository,
    SqlRuntimeSettingsRepository,
    SqlSessionRepository,
    SqlTaskRepository,
    SqlUserRepository,
)
from .services.agent import AgentService
from .services.auth import AuthService
from .services.documents import DocumentService
from .services.embeddings import EmbeddingService
from .services.extraction import ExtractionService
from .services.generation_service import GenerationService
from .services.query_understanding import QueryUnderstandingService
from .services.retrieval import RetrievalService
from .services.runtime_models import RuntimeModelService
from .services.runtime_retrieval import RuntimeRetrievalService
from .services.system import SystemService
from .services.tools import ToolService
from .services.users import UserService


class Container:
    def __init__(self) -> None:
        storage = Path(settings.storage_dir)
        if settings.database_url:
            database = SqlDatabase(settings.database_url)
            runtime_settings = SqlRuntimeSettingsRepository(database)
            self.conversations = SqlConversationRepository(database)
            self.documents = SqlDocumentRepository(database)
            self.document_tasks = SqlDocumentTaskRepository(database)
            self.users = SqlUserRepository(database)
            self.sessions = (
                SqlSessionRepository(database)
                if settings.persist_auth_sessions
                else SessionRepository(None)
            )
            self.tasks = SqlTaskRepository(database)
            self.runtime_retrieval_service = RuntimeRetrievalService(
                storage / "runtime_retrieval.json",
                runtime_store=runtime_settings,
            )
            self.runtime_model_service = RuntimeModelService(
                storage / "runtime_model.json",
                runtime_store=runtime_settings,
            )
        else:
            self.conversations = ConversationRepository(JsonStore(storage / "conversations.json"))
            self.documents = DocumentRepository(
                JsonStore(storage / "documents.json"),
                JsonStore(storage / "chunks.json"),
            )
            self.document_tasks = DocumentTaskRepository(JsonStore(storage / "document_tasks.json"))
            self.users = UserRepository(JsonStore(storage / "users.json"))
            session_store = JsonStore(storage / "sessions.json") if settings.persist_auth_sessions else None
            self.sessions = SessionRepository(session_store)
            self.tasks = TaskRepository(JsonStore(storage / "tasks.json"))
            self.runtime_retrieval_service = RuntimeRetrievalService(storage / "runtime_retrieval.json")
            self.runtime_model_service = RuntimeModelService(storage / "runtime_model.json")
        self.vector_store = self._build_vector_store()
        self.embedding_service = EmbeddingService()
        self.document_service = DocumentService(
            self.documents,
            self.document_tasks,
            self.vector_store,
            self.embedding_service,
        )
        self.extraction_service = ExtractionService()
        self.retrieval_service = RetrievalService(
            self.documents,
            self.vector_store,
            self.runtime_retrieval_service,
            self.embedding_service,
        )
        self.query_understanding_service = QueryUnderstandingService()
        self.tool_service = ToolService(self.retrieval_service)
        self.user_service = UserService(self.users)
        self.auth_service = AuthService(self.users, self.sessions)
        self.generation_service = GenerationService(self.runtime_model_service)
        self.agent_service = AgentService(
            retrieval=self.retrieval_service,
            tools=self.tool_service,
            tasks=self.tasks,
            generation=self.generation_service,
            query_understanding=self.query_understanding_service,
        )
        self.system_service = SystemService(
            self.conversations,
            self.documents,
            self.vector_store,
            self.tasks,
            self.runtime_model_service,
            self.runtime_retrieval_service,
            self.embedding_service,
        )

    def _build_vector_store(self) -> VectorStore:
        provider = settings.vector_store_provider.strip().lower()
        if provider == "local":
            return LocalVectorStore(self.documents)
        if provider == "milvus":
            return MilvusVectorStore(
                uri=settings.milvus_uri,
                token=settings.milvus_token,
                collection=settings.milvus_collection,
                dimension=settings.embedding_dimensions,
            )
        raise ValueError(
            "Unsupported AEGIS_VECTOR_STORE_PROVIDER "
            f"{settings.vector_store_provider!r}; expected 'local' or 'milvus'."
        )


@lru_cache(maxsize=1)
def get_container() -> Container:
    return Container()


def reset_container() -> None:
    get_container.cache_clear()


def get_current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    container = get_container()
    try:
        return container.auth_service.get_user_by_token(token)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录态已失效，请重新登录") from exc
