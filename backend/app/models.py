from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Intent(str, Enum):
    chitchat = "chitchat"
    knowledge_qa = "knowledge_qa"
    task = "task"


class WorkflowStep(str, Enum):
    clarification_check = "clarification_check"
    query_rewrite = "query_rewrite"
    query_expand = "query_expand"
    intent_detect = "intent_detect"
    intent_route = "intent_route"
    retrieve_context = "retrieve_context"
    plan_response = "plan_response"
    tool_or_answer = "tool_or_answer"
    response_grounding_check = "response_grounding_check"
    final_response = "final_response"


class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"
    system = "system"


class UserRole(str, Enum):
    admin = "admin"
    member = "member"


class DocumentIndexState(str, Enum):
    pending = "pending"
    indexing = "indexing"
    indexed = "indexed"
    failed = "failed"


class DocumentTaskKind(str, Enum):
    upload = "upload"
    reindex = "reindex"


class DocumentTaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class RetrievalStrategy(str, Enum):
    hybrid = "hybrid"


class Message(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    role: MessageRole
    content: str
    created_at: datetime = Field(default_factory=utc_now)


class Conversation(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    owner_id: str = "admin"
    title: str = "新对话"
    messages: list[Message] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Document(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    source_type: str = "text"
    department: str = "general"
    version: str = "v1"
    content: str
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    indexed_at: datetime | None = None
    index_state: DocumentIndexState = DocumentIndexState.pending
    embedding_version: str = ""
    last_index_error: str = ""
    last_task_id: str | None = None
    last_upload_task_id: str | None = None


class Chunk(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    document_id: str
    document_title: str
    text: str
    chunk_index: int
    tokens: list[str]
    embedding: list[float] = Field(default_factory=list)
    embedding_version: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalResult(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    text: str
    score: float
    source: str
    display_source: str = ""
    retrieval_method: str = "hybrid"
    keyword_score: float = 0.0
    semantic_score: float = 0.0
    semantic_source: str = "heuristic"
    rerank_score: float = 0.0
    coverage_score: float = 0.0
    matched_query: str = ""
    query_variant: str = "primary"
    query_boost: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalSettings(BaseModel):
    strategy: RetrievalStrategy = RetrievalStrategy.hybrid
    top_k: int = 5
    candidate_k: int = 12
    keyword_weight: float = 0.55
    semantic_weight: float = 0.45
    rerank_weight: float = 0.6
    min_score: float = 0.08


class ModelOption(BaseModel):
    id: str
    label: str
    tier: str
    description: str
    recommended_for: str


class ModelCatalog(BaseModel):
    provider: str
    base_url: str
    active_model: str
    api_key_configured: bool
    options: list[ModelOption] = Field(default_factory=list)


class User(BaseModel):
    id: str
    name: str
    role: UserRole
    created_at: datetime = Field(default_factory=utc_now)


class AuthSession(BaseModel):
    token: str = Field(default_factory=lambda: uuid4().hex)
    user_id: str
    created_at: datetime = Field(default_factory=utc_now)
    last_seen_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime = Field(default_factory=utc_now)


class AgentTask(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str = "admin"
    conversation_id: str
    query: str
    intent: Intent
    steps: list[WorkflowStep]
    trace: list[dict[str, Any]] = Field(default_factory=list)
    final_answer: str = ""
    citations: list[RetrievalResult] = Field(default_factory=list)
    route_reason: str = ""
    provider: str = "mock"
    created_at: datetime = Field(default_factory=utc_now)


class DocumentTask(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str = "admin"
    document_id: str | None = None
    document_title: str = ""
    kind: DocumentTaskKind
    status: DocumentTaskStatus = DocumentTaskStatus.pending
    progress: int = 0
    message: str = ""
    error: str = ""
    chunks_created: int = 0
    queued_at: datetime | None = None
    started_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class EvaluationCase(BaseModel):
    id: str
    question: str
    expected_keywords: list[str]
    expected_document: str


class EvaluationRun(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    cases: int
    answer_rate: float
    citation_hit_rate: float
    keyword_hit_rate: float
    details: list[dict[str, Any]]
    created_at: datetime = Field(default_factory=utc_now)


class SystemStats(BaseModel):
    documents: int
    indexed_chunks: int
    conversations: int
    tasks: int
    retrieval_top_k: int
    retrieval_candidate_k: int
    retrieval_strategy: str
    grounding_threshold: float
    llm_provider: str
    llm_model: str
    embedding_provider: str = ""
    embedding_model: str = ""
    current_embedding_version: str = ""
    embedding_dimensions: int = 0
    embedded_documents: int = 0
    embedded_chunks: int = 0
    pending_embedding_documents: int = 0
    stale_embedding_documents: int = 0
    api_key_configured: bool = False
    embedding_api_key_configured: bool = False


class SystemCheck(BaseModel):
    status: str
    message: str = ""
    provider: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)


class SystemStatus(BaseModel):
    status: str
    ready: bool
    providers: dict[str, SystemCheck]
    document_tasks: dict[str, int]
