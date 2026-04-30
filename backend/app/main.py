from __future__ import annotations

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware

from .api_schemas import (
    AgentTaskDetailResponse,
    AgentTaskListResponse,
    AgentTaskSummary,
    BulkReindexRequest,
    BulkReindexResponse,
    ChatRequest,
    ChatResponse,
    ConversationCreateRequest,
    ConversationListResponse,
    CurrentUserResponse,
    DocumentCreateRequest,
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentStatusResponse,
    DocumentSummary,
    DocumentTaskResponse,
    DocumentTaskSummary,
    DocumentUploadResponse,
    EvaluationResponse,
    IndexResponse,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    ModelCatalogResponse,
    ModelSelectRequest,
    ReindexResponse,
    RetrievalDebugRequest,
    RetrievalDebugResponse,
    RetrievalPreviewRequest,
    RetrievalPreviewResponse,
    RetrievalSettingsResponse,
    RetrievalSettingsUpdateRequest,
    SystemStatsResponse,
    SystemStatusResponse,
    QueryUnderstandingPreview,
    UserListResponse,
)
from .config import settings
from .deps import get_container, get_current_user
from .models import (
    AgentTask,
    Document,
    DocumentIndexState,
    DocumentTask,
    DocumentTaskKind,
    DocumentTaskStatus,
    Intent,
    Message,
    MessageRole,
    RetrievalSettings,
    User,
    UserRole,
)
from .seed import main as seed_sample_documents
from .services.evaluation import EvaluationService
from .services.extraction import ExtractionError
from .services.streaming import sse_event, stream_response
from .services.text import normalize_text

app = FastAPI(title=settings.app_name, version=settings.app_version)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:5174",
        "http://localhost:5174",
        "http://127.0.0.1:5175",
        "http://localhost:5175",
    ],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
seed_sample_documents()


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "AegisCopilot API is running", "environment": settings.environment}


@app.get("/health")
def health() -> dict[str, str]:
    container = get_container()
    runtime = container.runtime_model_service.get_runtime()
    return {"status": "ok", "provider": str(runtime["provider"]), "model": str(runtime["model"])}


def _require_admin(user: User) -> None:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    return token


def _friendly_source_type(source_type: str) -> str:
    normalized = source_type.strip().lower()
    return {
        "upload": "上传文件",
        "seed": "示例文档",
        "text": "手动录入",
        "pdf": "PDF",
        "docx": "Word",
        "markdown": "Markdown",
    }.get(normalized, source_type.replace("_", " ").title())


def _friendly_index_state(index_state: DocumentIndexState) -> str:
    return {
        DocumentIndexState.pending: "待索引",
        DocumentIndexState.indexing: "索引中",
        DocumentIndexState.indexed: "已索引",
        DocumentIndexState.failed: "索引失败",
    }[index_state]


def _friendly_task_kind(kind: DocumentTaskKind) -> str:
    return {
        DocumentTaskKind.upload: "上传入库",
        DocumentTaskKind.reindex: "重建索引",
    }[kind]


def _friendly_task_status(status_value: DocumentTaskStatus) -> str:
    return {
        DocumentTaskStatus.pending: "等待中",
        DocumentTaskStatus.running: "执行中",
        DocumentTaskStatus.succeeded: "已完成",
        DocumentTaskStatus.failed: "失败",
    }[status_value]


def _build_task_summary(task: DocumentTask | None) -> DocumentTaskSummary | None:
    if task is None:
        return None
    return DocumentTaskSummary(
        **task.model_dump(mode="json"),
        kind_label=_friendly_task_kind(task.kind),
        status_label=_friendly_task_status(task.status),
    )


def _build_document_summary(document: Document, chunk_count: int, task: DocumentTask | None = None) -> DocumentSummary:
    indexed = document.index_state == DocumentIndexState.indexed and bool(document.indexed_at)
    preview = normalize_text(document.content)[:160]
    container = get_container()
    current_embedding_version = container.document_service.get_current_embedding_version()
    embedded_chunk_count = container.vector_store.count_embedded_chunks_for_document(document.id)
    missing_embedding_chunks = max(chunk_count - embedded_chunk_count, 0)
    embedding_stale = (
        container.embedding_service.is_enabled()
        and chunk_count > 0
        and embedded_chunk_count > 0
        and document.embedding_version != current_embedding_version
    )
    if document.index_state == DocumentIndexState.indexed:
        indexed_label = f"已索引，共 {chunk_count} 个片段"
    elif document.index_state == DocumentIndexState.failed and document.last_index_error:
        indexed_label = f"索引失败：{document.last_index_error}"
    elif document.index_state == DocumentIndexState.indexing:
        indexed_label = "索引任务进行中"
    else:
        indexed_label = "尚未建立索引"
    if chunk_count <= 0 and document.index_state == DocumentIndexState.indexed:
        embedding_label = "已索引，但暂无可向量化片段"
    elif chunk_count <= 0:
        embedding_label = "尚未完成索引，暂不可向量化"
    elif embedding_stale:
        embedding_label = "向量版本已过期，建议重建索引"
    elif missing_embedding_chunks == 0:
        embedding_label = f"向量已补齐，共 {embedded_chunk_count} 个片段"
    else:
        embedding_label = f"待补齐 {missing_embedding_chunks} / {chunk_count} 个片段"

    return DocumentSummary(
        **document.model_dump(mode="json"),
        chunk_count=chunk_count,
        indexed=indexed,
        index_state_label=_friendly_index_state(document.index_state),
        indexed_label=indexed_label,
        embedded_chunk_count=embedded_chunk_count,
        missing_embedding_chunks=missing_embedding_chunks,
        embedding_ready=chunk_count > 0 and missing_embedding_chunks == 0 and not embedding_stale,
        embedding_stale=embedding_stale,
        current_embedding_version=current_embedding_version,
        embedding_label=embedding_label,
        source_label=f"{_friendly_source_type(document.source_type)} / {document.department}",
        tag_count=len(document.tags),
        content_preview=preview,
        last_task=_build_task_summary(task),
    )


def _document_matches(
    summary: DocumentSummary,
    *,
    query: str | None,
    department: str | None,
    source_type: str | None,
    index_state: str | None,
    indexed: bool | None,
    tag: str | None,
) -> bool:
    if department and summary.department.lower() != department.strip().lower():
        return False
    if source_type and summary.source_type.lower() != source_type.strip().lower():
        return False
    if index_state and summary.index_state.value != index_state.strip().lower():
        return False
    if indexed is not None and summary.indexed != indexed:
        return False
    if tag:
        needle = tag.strip().lower()
        if not any(needle in item.lower() for item in summary.tags):
            return False
    if query:
        needle = normalize_text(query).lower()
        haystack = " ".join(
            [
                summary.title,
                summary.content,
                summary.department,
                summary.source_type,
                summary.version,
                summary.index_state.value,
                " ".join(summary.tags),
            ]
        ).lower()
        if needle not in haystack:
            return False
    return True


def _sort_documents(documents: list[DocumentSummary], sort_by: str) -> list[DocumentSummary]:
    key = sort_by.strip().lower()
    if key == "title_asc":
        return sorted(documents, key=lambda item: item.title.lower())
    if key == "title_desc":
        return sorted(documents, key=lambda item: item.title.lower(), reverse=True)
    if key == "created_asc":
        return sorted(documents, key=lambda item: item.created_at)
    if key == "created_desc":
        return sorted(documents, key=lambda item: item.created_at, reverse=True)
    return sorted(documents, key=lambda item: (item.updated_at, item.title.lower()), reverse=True)


def _ensure_conversation_owner(conversation, current_user: User) -> None:
    if conversation.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")


def _ensure_task_owner(task, current_user: User) -> None:
    if task.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")


def _ensure_task_access(task: AgentTask, current_user: User) -> None:
    if current_user.role == UserRole.admin:
        return
    _ensure_task_owner(task, current_user)


def _document_counts() -> dict[str, int]:
    container = get_container()
    counts: dict[str, int] = {}
    for chunk in container.vector_store.list_chunks():
        counts[chunk.document_id] = counts.get(chunk.document_id, 0) + 1
    return counts


def _document_task_map(documents: list[Document]) -> dict[str, DocumentTask]:
    container = get_container()
    task_map: dict[str, DocumentTask] = {}
    for document in documents:
        if not document.last_task_id:
            continue
        task = container.document_tasks.get(document.last_task_id)
        if task is not None:
            task_map[document.last_task_id] = task
    return task_map


def _friendly_intent(intent: Intent) -> str:
    return {
        Intent.chitchat: "寒暄闲聊",
        Intent.knowledge_qa: "知识问答",
        Intent.task: "任务整理",
    }[intent]


def _task_grounded(task: AgentTask) -> bool:
    for item in reversed(task.trace):
        if item.get("step") == "response_grounding_check":
            return bool(item.get("grounded"))
    return False


def _task_top_score(task: AgentTask) -> float:
    if task.citations:
        return float(task.citations[0].score)
    for item in reversed(task.trace):
        if item.get("step") == "response_grounding_check":
            try:
                return float(item.get("top_score", 0.0))
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _build_agent_task_summary(task: AgentTask) -> AgentTaskSummary:
    return AgentTaskSummary(
        id=task.id,
        user_id=task.user_id,
        conversation_id=task.conversation_id,
        query=task.query,
        intent=task.intent.value,
        intent_label=_friendly_intent(task.intent),
        grounded=_task_grounded(task),
        top_score=round(_task_top_score(task), 4),
        citations_count=len(task.citations),
        trace_steps=len(task.trace),
        route_reason=task.route_reason,
        final_answer_preview=task.final_answer[:180],
        provider=task.provider,
        created_at=task.created_at.isoformat(),
    )


@app.post("/auth/login", response_model=LoginResponse)
def login(request: LoginRequest) -> LoginResponse:
    container = get_container()
    try:
        user, session = container.auth_service.login(request.username, request.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return LoginResponse(
        token=session.token,
        user=container.user_service.summarize_user(user),
        session_expires_at=session.expires_at,
        demo_mode=settings.allow_demo_auth,
    )


@app.post("/auth/logout", response_model=LogoutResponse)
def logout(
    authorization: str | None = Header(default=None, alias="Authorization"),
    current_user: User = Depends(get_current_user),
) -> LogoutResponse:
    container = get_container()
    container.auth_service.logout(_extract_bearer_token(authorization))
    return LogoutResponse(success=True)


@app.get("/auth/me", response_model=CurrentUserResponse)
def auth_me(current_user: User = Depends(get_current_user)) -> CurrentUserResponse:
    container = get_container()
    return CurrentUserResponse(user=container.user_service.summarize_user(current_user))


@app.get("/system/stats", response_model=SystemStatsResponse)
def get_system_stats(current_user: User = Depends(get_current_user)) -> SystemStatsResponse:
    container = get_container()
    return SystemStatsResponse(stats=container.system_service.get_stats(current_user))


@app.get("/system/status", response_model=SystemStatusResponse)
def get_system_status(current_user: User = Depends(get_current_user)) -> SystemStatusResponse:
    _require_admin(current_user)
    container = get_container()
    return SystemStatusResponse(status=container.system_service.get_status())


@app.get("/users", response_model=UserListResponse)
def list_users(current_user: User = Depends(get_current_user)) -> UserListResponse:
    _require_admin(current_user)
    container = get_container()
    return UserListResponse(users=container.user_service.list_user_summaries())


@app.get("/users/me", response_model=CurrentUserResponse)
def get_me(current_user: User = Depends(get_current_user)) -> CurrentUserResponse:
    container = get_container()
    return CurrentUserResponse(user=container.user_service.summarize_user(current_user))


@app.get("/models", response_model=ModelCatalogResponse)
def get_model_catalog(current_user: User = Depends(get_current_user)) -> ModelCatalogResponse:
    container = get_container()
    return ModelCatalogResponse(catalog=container.runtime_model_service.get_catalog())


@app.post("/models/select", response_model=ModelCatalogResponse)
def select_model(
    request: ModelSelectRequest,
    current_user: User = Depends(get_current_user),
) -> ModelCatalogResponse:
    container = get_container()
    _require_admin(current_user)
    try:
        catalog = container.runtime_model_service.select_model(request.model_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ModelCatalogResponse(catalog=catalog)


@app.get("/retrieval/settings", response_model=RetrievalSettingsResponse)
def get_retrieval_settings(current_user: User = Depends(get_current_user)) -> RetrievalSettingsResponse:
    container = get_container()
    return RetrievalSettingsResponse(settings=container.retrieval_service.get_runtime_settings())


@app.post("/retrieval/settings", response_model=RetrievalSettingsResponse)
def update_retrieval_settings(
    request: RetrievalSettingsUpdateRequest,
    current_user: User = Depends(get_current_user),
) -> RetrievalSettingsResponse:
    _require_admin(current_user)
    container = get_container()
    try:
        retrieval_settings = container.retrieval_service.update_runtime_settings(**request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return RetrievalSettingsResponse(settings=retrieval_settings)


@app.get("/conversations", response_model=ConversationListResponse)
def list_conversations(current_user: User = Depends(get_current_user)) -> ConversationListResponse:
    container = get_container()
    return ConversationListResponse(conversations=container.conversations.list_for_user(current_user.id))


@app.post("/conversations", response_model=dict)
def create_conversation(
    request: ConversationCreateRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    container = get_container()
    conversation = container.conversations.create(title=request.title, owner_id=current_user.id)
    return {"conversation": conversation}


@app.get("/conversations/{conversation_id}", response_model=dict)
def get_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
) -> dict:
    container = get_container()
    conversation = container.conversations.get(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    _ensure_conversation_owner(conversation, current_user)
    return {"conversation": conversation}


@app.delete("/conversations/{conversation_id}", response_model=dict)
def delete_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
) -> dict:
    container = get_container()
    conversation = container.conversations.get(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    _ensure_conversation_owner(conversation, current_user)
    container.conversations.delete(conversation_id)
    return {"deleted": True, "conversation_id": conversation_id}


@app.get("/documents", response_model=DocumentListResponse)
def list_documents(
    q: str | None = None,
    department: str | None = None,
    source_type: str | None = None,
    index_state: str | None = None,
    indexed: bool | None = None,
    tag: str | None = None,
    limit: int | None = None,
    sort_by: str = "updated_desc",
    current_user: User = Depends(get_current_user),
) -> DocumentListResponse:
    container = get_container()
    documents = container.document_service.list_documents()
    counts = _document_counts()
    task_map = _document_task_map(documents)

    summaries = [
        _build_document_summary(document, counts.get(document.id, 0), task_map.get(document.last_task_id or ""))
        for document in documents
    ]
    summaries = [
        document
        for document in summaries
        if _document_matches(
            document,
            query=q,
            department=department,
            source_type=source_type,
            index_state=index_state,
            indexed=indexed,
            tag=tag,
        )
    ]
    summaries = _sort_documents(summaries, sort_by)
    if limit is not None and limit >= 0:
        summaries = summaries[:limit]
    return DocumentListResponse(documents=summaries)


@app.get("/documents/{document_id}", response_model=DocumentDetailResponse)
def get_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
) -> DocumentDetailResponse:
    container = get_container()
    document = container.document_service.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")

    chunk_count = container.vector_store.count_chunks_for_document(document_id)
    latest_task = container.document_tasks.get(document.last_task_id) if document.last_task_id else None
    summary = _build_document_summary(document, chunk_count, latest_task)
    chunks = [
        {
            "id": chunk.id,
            "document_id": chunk.document_id,
            "document_title": chunk.document_title,
            "chunk_index": chunk.chunk_index,
            "text_preview": normalize_text(chunk.text)[:240],
            "token_count": len(chunk.tokens),
            "metadata": chunk.metadata,
        }
        for chunk in container.vector_store.list_chunks_for_document(document_id)
    ]
    recent_tasks = [
        _build_task_summary(task)
        for task in container.document_service.list_document_tasks(document_id, limit=6)
    ]
    return DocumentDetailResponse(
        document=summary,
        chunks=chunks,
        recent_tasks=[task for task in recent_tasks if task is not None],
    )


@app.get("/documents/{document_id}/status", response_model=DocumentStatusResponse)
def get_document_status(
    document_id: str,
    current_user: User = Depends(get_current_user),
) -> DocumentStatusResponse:
    container = get_container()
    document = container.document_service.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    task = container.document_tasks.get(document.last_task_id) if document.last_task_id else None
    summary = _build_document_summary(
        document,
        container.vector_store.count_chunks_for_document(document_id),
        task,
    )
    return DocumentStatusResponse(document=summary, task=_build_task_summary(task))


@app.post("/documents", response_model=dict)
def create_document(
    request: DocumentCreateRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    container = get_container()
    _require_admin(current_user)
    document = container.document_service.create_document(**request.model_dump())
    summary = _build_document_summary(document, 0)
    return {"document": summary}


@app.delete("/documents/{document_id}", response_model=dict)
def delete_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
) -> dict:
    container = get_container()
    _require_admin(current_user)
    deleted = container.document_service.delete_document(document_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    return {"deleted": True, "document_id": document_id}


@app.post("/documents/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> DocumentUploadResponse:
    container = get_container()
    _require_admin(current_user)
    raw = await file.read()
    filename = file.filename or "uploaded-file"
    try:
        content = container.extraction_service.extract(filename, raw)
    except ExtractionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    document, task, chunks_created = container.document_service.import_document(
        user_id=current_user.id,
        title=filename,
        content=normalize_text(content),
        source_type="upload",
        department="general",
        version="v1",
        tags=[],
    )
    summary = _build_document_summary(document, container.vector_store.count_chunks_for_document(document.id), task)
    return DocumentUploadResponse(
        document=summary,
        task=_build_task_summary(task),
        chunks_created=chunks_created,
    )


@app.get("/documents/upload/tasks/{task_id}", response_model=DocumentTaskResponse)
def get_upload_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
) -> DocumentTaskResponse:
    _require_admin(current_user)
    container = get_container()
    task = container.document_service.get_document_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="上传任务不存在")
    return DocumentTaskResponse(task=_build_task_summary(task))


@app.post("/documents/{document_id}/reindex", response_model=ReindexResponse)
def reindex_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
) -> ReindexResponse:
    container = get_container()
    _require_admin(current_user)
    try:
        document, task, chunks_created = container.document_service.reindex_document(document_id, current_user.id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在") from exc
    summary = _build_document_summary(document, container.vector_store.count_chunks_for_document(document.id), task)
    return ReindexResponse(
        document=summary,
        task=_build_task_summary(task),
        chunks_created=chunks_created,
    )


@app.post("/documents/reindex-batch", response_model=BulkReindexResponse)
def bulk_reindex_documents(
    request: BulkReindexRequest,
    current_user: User = Depends(get_current_user),
) -> BulkReindexResponse:
    container = get_container()
    _require_admin(current_user)
    try:
        result = container.document_service.bulk_reindex(user_id=current_user.id, mode=request.mode)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return BulkReindexResponse(**result)


@app.post("/documents/index", response_model=IndexResponse)
def index_document(
    payload: dict[str, str],
    current_user: User = Depends(get_current_user),
) -> IndexResponse:
    _require_admin(current_user)
    document_id = payload.get("document_id")
    if not document_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少 document_id")
    container = get_container()
    try:
        chunks_created = container.document_service.index_document(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return IndexResponse(document_id=document_id, chunks_created=chunks_created)


@app.post("/retrieval/preview", response_model=RetrievalPreviewResponse)
def preview_retrieval(
    request: RetrievalPreviewRequest,
    current_user: User = Depends(get_current_user),
) -> RetrievalPreviewResponse:
    container = get_container()
    understanding = container.query_understanding_service.analyze(None, request.query)
    results = []
    if not understanding.needs_clarification:
        primary_query = understanding.rewritten_query or request.query
        variant_queries = [item for item in understanding.retrieval_queries if item.lower() != primary_query.lower()]
        results = container.retrieval_service.search(primary_query, request.top_k, variant_queries)
    return RetrievalPreviewResponse(
        understanding=QueryUnderstandingPreview(
            original_query=understanding.original_query,
            rewritten_query=understanding.rewritten_query,
            retrieval_queries=understanding.retrieval_queries,
            expanded_queries=understanding.expanded_queries,
            intent=understanding.intent.value,
            route_reason=understanding.route_reason,
            needs_clarification=understanding.needs_clarification,
            clarification_reason=understanding.clarification_reason,
            clarification_prompt=understanding.clarification_prompt,
            history_topic=understanding.history_topic,
        ),
        results=results,
    )


@app.post("/retrieval/debug", response_model=RetrievalDebugResponse)
def debug_retrieval(
    request: RetrievalDebugRequest,
    current_user: User = Depends(get_current_user),
) -> RetrievalDebugResponse:
    _require_admin(current_user)
    container = get_container()
    understanding = container.query_understanding_service.analyze(None, request.query)
    primary_query = understanding.rewritten_query or request.query
    variant_queries = request.query_variants
    if not variant_queries and not understanding.needs_clarification:
        variant_queries = [item for item in understanding.retrieval_queries if item.lower() != primary_query.lower()]
    try:
        debug = container.retrieval_service.debug_search(
            primary_query,
            top_k=request.top_k,
            candidate_k=request.candidate_k,
            keyword_weight=request.keyword_weight,
            semantic_weight=request.semantic_weight,
            rerank_weight=request.rerank_weight,
            min_score=request.min_score,
            query_variants=variant_queries,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    debug["understanding"] = QueryUnderstandingPreview(
        original_query=understanding.original_query,
        rewritten_query=understanding.rewritten_query,
        retrieval_queries=understanding.retrieval_queries,
        expanded_queries=understanding.expanded_queries,
        intent=understanding.intent.value,
        route_reason=understanding.route_reason,
        needs_clarification=understanding.needs_clarification,
        clarification_reason=understanding.clarification_reason,
        clarification_prompt=understanding.clarification_prompt,
        history_topic=understanding.history_topic,
    ).model_dump(mode="json")
    return RetrievalDebugResponse(debug=debug)


@app.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
) -> ChatResponse:
    container = get_container()
    if request.conversation_id:
        conversation = container.conversations.get(request.conversation_id)
        if conversation is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
        _ensure_conversation_owner(conversation, current_user)
    else:
        conversation = container.conversations.create(title=request.query[:24], owner_id=current_user.id)

    user_message = Message(role=MessageRole.user, content=request.query)
    container.conversations.append_message(conversation.id, user_message)
    reply, task = container.agent_service.run(conversation, request.query)
    container.conversations.append_message(conversation.id, reply)
    return ChatResponse(conversation=conversation, reply=reply, task=task)


@app.post("/chat/stream")
def chat_stream(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    container = get_container()
    if request.conversation_id:
        conversation = container.conversations.get(request.conversation_id)
        if conversation is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
        _ensure_conversation_owner(conversation, current_user)
    else:
        conversation = container.conversations.create(title=request.query[:24], owner_id=current_user.id)

    user_message = Message(role=MessageRole.user, content=request.query)
    container.conversations.append_message(conversation.id, user_message)

    def event_generator():
        yield sse_event("conversation", {"conversation_id": conversation.id})
        for event in container.agent_service.run_stream(conversation, request.query):
            if event["type"] == "done":
                reply = Message.model_validate(event["reply"])
                container.conversations.append_message(conversation.id, reply)
            yield sse_event(event["type"], event)

    return stream_response(event_generator())


@app.get("/tasks", response_model=AgentTaskListResponse)
def list_tasks(
    q: str | None = None,
    intent: str | None = None,
    grounded: bool | None = None,
    user_id: str | None = None,
    limit: int = 30,
    current_user: User = Depends(get_current_user),
) -> AgentTaskListResponse:
    container = get_container()
    tasks = container.tasks.list() if current_user.role == UserRole.admin else container.tasks.list_for_user(current_user.id)
    filtered: list[AgentTask] = []
    for task in tasks:
        if user_id and current_user.role == UserRole.admin and task.user_id != user_id:
            continue
        if intent and task.intent.value != intent.strip().lower():
            continue
        if grounded is not None and _task_grounded(task) != grounded:
            continue
        if q:
            needle = normalize_text(q).lower()
            haystack = " ".join(
                [
                    task.query,
                    task.final_answer,
                    task.route_reason,
                    " ".join(citation.document_title for citation in task.citations),
                ]
            ).lower()
            if needle not in haystack:
                continue
        filtered.append(task)

    filtered.sort(key=lambda item: item.created_at, reverse=True)
    max_limit = max(1, min(limit, 100))
    return AgentTaskListResponse(tasks=[_build_agent_task_summary(task) for task in filtered[:max_limit]])


@app.get("/tasks/{task_id}", response_model=AgentTaskDetailResponse)
def get_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
) -> AgentTaskDetailResponse:
    container = get_container()
    task = container.tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    _ensure_task_access(task, current_user)
    return AgentTaskDetailResponse(summary=_build_agent_task_summary(task), task=task)


@app.post("/evaluate/run", response_model=EvaluationResponse)
def run_evaluation(current_user: User = Depends(get_current_user)) -> EvaluationResponse:
    _require_admin(current_user)
    container = get_container()
    service = EvaluationService(container.agent_service, container.conversations, current_user.id)
    return EvaluationResponse(run=service.run())
