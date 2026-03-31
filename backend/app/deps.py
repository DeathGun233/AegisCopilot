from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import Header, HTTPException, status

from .config import settings
from .models import User
from .repositories import (
    ConversationRepository,
    DocumentRepository,
    DocumentTaskRepository,
    JsonStore,
    SessionRepository,
    TaskRepository,
    UserRepository,
)
from .services.agent import AgentService
from .services.auth import AuthService
from .services.documents import DocumentService
from .services.extraction import ExtractionService
from .services.generation_service import GenerationService
from .services.retrieval import RetrievalService
from .services.runtime_models import RuntimeModelService
from .services.system import SystemService
from .services.tools import ToolService
from .services.users import UserService


class Container:
    def __init__(self) -> None:
        storage = Path(settings.storage_dir)
        self.conversations = ConversationRepository(JsonStore(storage / "conversations.json"))
        self.documents = DocumentRepository(
            JsonStore(storage / "documents.json"),
            JsonStore(storage / "chunks.json"),
        )
        self.document_tasks = DocumentTaskRepository(JsonStore(storage / "document_tasks.json"))
        self.users = UserRepository(JsonStore(storage / "users.json"))
        self.sessions = SessionRepository(JsonStore(storage / "sessions.json"))
        self.tasks = TaskRepository(JsonStore(storage / "tasks.json"))
        self.document_service = DocumentService(self.documents, self.document_tasks)
        self.extraction_service = ExtractionService()
        self.retrieval_service = RetrievalService(self.documents)
        self.tool_service = ToolService(self.retrieval_service)
        self.runtime_model_service = RuntimeModelService(storage / "runtime_model.json")
        self.user_service = UserService(self.users)
        self.auth_service = AuthService(self.users, self.sessions)
        self.generation_service = GenerationService(self.runtime_model_service)
        self.agent_service = AgentService(
            retrieval=self.retrieval_service,
            tools=self.tool_service,
            tasks=self.tasks,
            generation=self.generation_service,
        )
        self.system_service = SystemService(
            self.conversations,
            self.documents,
            self.tasks,
            self.runtime_model_service,
        )


@lru_cache(maxsize=1)
def get_container() -> Container:
    return Container()


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
