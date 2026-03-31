from __future__ import annotations

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware

from .api_schemas import (
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
    RetrievalPreviewRequest,
    RetrievalPreviewResponse,
    SystemStatsResponse,
    UserListResponse,
)
from .config import settings
from .deps import get_container, get_current_user
from .models import (
    Document,
    DocumentIndexState,
    DocumentTask,
    DocumentTaskKind,
    DocumentTaskStatus,
    Message,
    MessageRole,
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
    index_label = _friendly_index_state(document.index_state)
    if document.index_state == DocumentIndexState.indexed:
        indexed_label = f"已索引，共 {chunk_count} 个片段"
    elif document.index_state == DocumentIndexState.failed and document.last_index_error:
        indexed_label = f"索引失败：{document.last_index_error}"
    elif document.index_state == DocumentIndexState.indexing:
        indexed_label = "索引任务进行中"
    else:
        indexed_label = "尚未建立索引"

    return DocumentSummary(
        **document.model_dump(mode="json"),
        chunk_count=chunk_count,
        indexed=indexed,
        index_state_label=index_label,
        indexed_label=indexed_label,
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


def _document_counts() -> dict[str, int]:
    container = get_container()
    counts: dict[str, int] = {}
    for chunk in container.documents.list_chunks():
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


@app.post("/auth/login", response_model=LoginResponse)
def login(request: LoginRequest) -> LoginResponse:
    container = get_container()
    try:
        user, session = container.auth_service.login(request.username, request.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return LoginResponse(token=session.token, user=container.user_service.summarize_user(user))


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

    chunk_count = container.documents.count_chunks_for_document(document_id)
    latest_task = (
        container.document_tasks.get(document.last_task_id) if document.last_task_id else None
    )
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
        for chunk in container.documents.list_chunks_for_document(document_id)
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
        container.documents.count_chunks_for_document(document_id),
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
    summary = _build_document_summary(document, chunks_created, task)
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
    summary = _build_document_summary(document, chunks_created, task)
    return ReindexResponse(
        document=summary,
        task=_build_task_summary(task),
        chunks_created=chunks_created,
    )


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
        _, _, chunks_created = container.document_service.reindex_document(document_id, current_user.id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在") from exc
    return IndexResponse(document_id=document_id, chunks_created=chunks_created)


@app.post("/retrieval/preview", response_model=RetrievalPreviewResponse)
def preview_retrieval(
    request: RetrievalPreviewRequest,
    current_user: User = Depends(get_current_user),
) -> RetrievalPreviewResponse:
    container = get_container()
    return RetrievalPreviewResponse(results=container.retrieval_service.search(request.query, request.top_k))


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


@app.get("/tasks/{task_id}", response_model=dict)
def get_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
) -> dict:
    container = get_container()
    task = container.tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    _ensure_task_owner(task, current_user)
    return {"task": task}


@app.post("/evaluate/run", response_model=EvaluationResponse)
def run_evaluation(current_user: User = Depends(get_current_user)) -> EvaluationResponse:
    _require_admin(current_user)
    container = get_container()
    service = EvaluationService(container.agent_service, container.conversations, current_user.id)
    return EvaluationResponse(run=service.run())
