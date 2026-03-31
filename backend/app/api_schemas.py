from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .models import (
    AgentTask,
    Conversation,
    Document,
    DocumentTask,
    EvaluationRun,
    Message,
    ModelCatalog,
    RetrievalResult,
    RetrievalSettings,
    SystemStats,
    User,
)


class DocumentTaskSummary(DocumentTask):
    kind_label: str = ""
    status_label: str = ""


class DocumentSummary(Document):
    chunk_count: int = 0
    indexed: bool = False
    index_state_label: str = "待索引"
    indexed_label: str = "未索引"
    source_label: str = ""
    tag_count: int = 0
    content_preview: str = ""
    last_task: DocumentTaskSummary | None = None


class ChunkSummary(BaseModel):
    id: str
    document_id: str
    document_title: str
    chunk_index: int
    text_preview: str
    token_count: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentDetailResponse(BaseModel):
    document: DocumentSummary
    chunks: list[ChunkSummary] = Field(default_factory=list)
    recent_tasks: list[DocumentTaskSummary] = Field(default_factory=list)


class DocumentStatusResponse(BaseModel):
    document: DocumentSummary
    task: DocumentTaskSummary | None = None


class DocumentTaskResponse(BaseModel):
    task: DocumentTaskSummary


class DocumentUploadResponse(BaseModel):
    document: DocumentSummary
    task: DocumentTaskSummary
    chunks_created: int


class ReindexResponse(BaseModel):
    document: DocumentSummary
    task: DocumentTaskSummary
    chunks_created: int


class ChatRequest(BaseModel):
    query: str = Field(min_length=1)
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    conversation: Conversation
    reply: Message
    task: AgentTask


class ConversationCreateRequest(BaseModel):
    title: str = "新对话"


class DocumentCreateRequest(BaseModel):
    title: str
    content: str
    source_type: str = "text"
    department: str = "general"
    version: str = "v1"
    tags: list[str] = Field(default_factory=list)


class DocumentListResponse(BaseModel):
    documents: list[DocumentSummary]


class IndexResponse(BaseModel):
    document_id: str
    chunks_created: int


class ConversationListResponse(BaseModel):
    conversations: list[Conversation]


class RetrievalPreviewRequest(BaseModel):
    query: str
    top_k: int | None = None


class RetrievalPreviewResponse(BaseModel):
    results: list[RetrievalResult]


class RetrievalSettingsUpdateRequest(BaseModel):
    top_k: int = Field(ge=1, le=10)
    candidate_k: int = Field(ge=1, le=40)
    keyword_weight: float = Field(ge=0)
    semantic_weight: float = Field(ge=0)
    rerank_weight: float = Field(ge=0)
    min_score: float = Field(ge=0, le=1)


class RetrievalSettingsResponse(BaseModel):
    settings: RetrievalSettings


class ModelSelectRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    model_id: str


class ModelCatalogResponse(BaseModel):
    catalog: ModelCatalog


class UserSummary(User):
    role_label: str = ""
    can_manage_knowledge: bool = False
    can_manage_models: bool = False
    permissions: list[str] = Field(default_factory=list)


class UserListResponse(BaseModel):
    users: list[UserSummary]


class CurrentUserResponse(BaseModel):
    user: UserSummary


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    token: str
    user: UserSummary


class LogoutResponse(BaseModel):
    success: bool = True


class EvaluationResponse(BaseModel):
    run: EvaluationRun


class SystemStatsResponse(BaseModel):
    stats: SystemStats
