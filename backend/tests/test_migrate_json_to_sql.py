from __future__ import annotations

import importlib.util
import json
from datetime import timedelta
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "migrate_json_to_sql.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("migrate_json_to_sql", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _dump_models(path: Path, models: list[object]) -> None:
    path.write_text(
        json.dumps([model.model_dump(mode="json") for model in models], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_migration_script_moves_runtime_settings_into_sqlite(tmp_path: Path) -> None:
    module = _load_module()
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)
    (storage_dir / "runtime_model.json").write_text(
        json.dumps({"active_model": "qwen-plus"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (storage_dir / "runtime_retrieval.json").write_text(
        json.dumps(
            {
                "strategy": "hybrid",
                "top_k": 6,
                "candidate_k": 16,
                "keyword_weight": 0.6,
                "semantic_weight": 0.4,
                "rerank_weight": 0.5,
                "min_score": 0.11,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    database_url = f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"

    assert module.main(["--storage-dir", str(storage_dir), "--database-url", database_url]) == 0

    from app.services.runtime_models import RuntimeModelService
    from app.services.runtime_retrieval import RuntimeRetrievalService
    from app.sql_repositories import SqlDatabase, SqlRuntimeSettingsRepository

    runtime_repo = SqlRuntimeSettingsRepository(SqlDatabase(database_url))
    model_service = RuntimeModelService(storage_path=storage_dir / "runtime_model.json", runtime_store=runtime_repo)
    retrieval_service = RuntimeRetrievalService(
        storage_path=storage_dir / "runtime_retrieval.json",
        runtime_store=runtime_repo,
    )

    assert model_service.get_active_model() == "qwen-plus"
    assert retrieval_service.get_settings().top_k == 6
    assert retrieval_service.get_settings().candidate_k == 16


def test_migration_script_moves_core_json_records_into_sqlite(tmp_path: Path) -> None:
    module = _load_module()
    from app.models import (
        AgentTask,
        AuthSession,
        Chunk,
        Conversation,
        Document,
        DocumentIndexState,
        DocumentTask,
        DocumentTaskKind,
        DocumentTaskStatus,
        Intent,
        Message,
        MessageRole,
        RetrievalResult,
        User,
        UserRole,
        WorkflowStep,
        utc_now,
    )
    from app.services.runtime_models import RuntimeModelService
    from app.services.runtime_retrieval import RuntimeRetrievalService
    from app.sql_repositories import (
        SqlConversationRepository,
        SqlDatabase,
        SqlDocumentRepository,
        SqlDocumentTaskRepository,
        SqlRuntimeSettingsRepository,
        SqlSessionRepository,
        SqlTaskRepository,
        SqlUserRepository,
    )

    storage_dir = tmp_path / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)
    now = utc_now()

    admin = User(id="admin", name="admin", role=UserRole.admin, created_at=now)
    member = User(id="member", name="member", role=UserRole.member, created_at=now)
    conversation = Conversation(
        id="conv-1",
        owner_id="admin",
        title="Migration Conversation",
        messages=[
            Message(id="msg-1", role=MessageRole.user, content="hello", created_at=now),
            Message(id="msg-2", role=MessageRole.assistant, content="world", created_at=now),
        ],
        created_at=now,
        updated_at=now,
    )
    document = Document(
        id="doc-1",
        title="Migration Document",
        source_type="text",
        department="ops",
        version="v1",
        content="Database migration content",
        tags=["migration"],
        created_at=now,
        updated_at=now,
        indexed_at=now,
        index_state=DocumentIndexState.indexed,
        embedding_version="test-v1",
        last_task_id="doc-task-1",
        last_upload_task_id="doc-task-1",
    )
    chunk = Chunk(
        id="chunk-1",
        document_id=document.id,
        document_title=document.title,
        text="Database migration content",
        chunk_index=0,
        tokens=["database", "migration"],
        embedding=[0.1, 0.2],
        embedding_version="test-v1",
        metadata={"department": "ops"},
    )
    document_task = DocumentTask(
        id="doc-task-1",
        user_id="admin",
        document_id=document.id,
        document_title=document.title,
        kind=DocumentTaskKind.upload,
        status=DocumentTaskStatus.succeeded,
        progress=100,
        message="done",
        chunks_created=1,
        created_at=now,
        updated_at=now,
        completed_at=now,
    )
    agent_task = AgentTask(
        id="task-1",
        user_id="admin",
        conversation_id=conversation.id,
        query="What changed?",
        intent=Intent.knowledge_qa,
        steps=[WorkflowStep.intent_detect, WorkflowStep.final_response],
        trace=[{"step": "intent_detect"}],
        final_answer="Migration is complete.",
        citations=[
            RetrievalResult(
                chunk_id=chunk.id,
                document_id=document.id,
                document_title=document.title,
                text=chunk.text,
                score=0.88,
                source="knowledge_base",
            )
        ],
        route_reason="knowledge",
        provider="mock",
        created_at=now,
    )
    session = AuthSession(
        token="session-1",
        user_id="admin",
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=4),
    )

    _dump_models(storage_dir / "conversations.json", [conversation])
    _dump_models(storage_dir / "documents.json", [document])
    _dump_models(storage_dir / "chunks.json", [chunk])
    _dump_models(storage_dir / "document_tasks.json", [document_task])
    _dump_models(storage_dir / "tasks.json", [agent_task])
    _dump_models(storage_dir / "users.json", [admin, member])
    _dump_models(storage_dir / "sessions.json", [session])
    (storage_dir / "runtime_model.json").write_text(
        json.dumps({"active_model": "qwen-plus"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (storage_dir / "runtime_retrieval.json").write_text(
        json.dumps(
            {
                "strategy": "hybrid",
                "top_k": 6,
                "candidate_k": 14,
                "keyword_weight": 0.6,
                "semantic_weight": 0.4,
                "rerank_weight": 0.5,
                "min_score": 0.15,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    database_url = f"sqlite:///{(tmp_path / 'full-migrated.db').as_posix()}"

    assert module.main(["--storage-dir", str(storage_dir), "--database-url", database_url]) == 0

    database = SqlDatabase(database_url)
    conversations = SqlConversationRepository(database)
    documents = SqlDocumentRepository(database)
    document_tasks = SqlDocumentTaskRepository(database)
    tasks = SqlTaskRepository(database)
    users = SqlUserRepository(database)
    sessions = SqlSessionRepository(database)
    runtime_repo = SqlRuntimeSettingsRepository(database)
    runtime_models = RuntimeModelService(storage_path=storage_dir / "runtime_model.json", runtime_store=runtime_repo)
    runtime_retrieval = RuntimeRetrievalService(
        storage_path=storage_dir / "runtime_retrieval.json",
        runtime_store=runtime_repo,
    )

    assert conversations.get(conversation.id) is not None
    assert documents.get_document(document.id) is not None
    assert len(documents.list_chunks_for_document(document.id)) == 1
    assert document_tasks.get(document_task.id) is not None
    assert tasks.get(agent_task.id) is not None
    assert users.get(admin.id) is not None
    assert sessions.get(session.token) is not None
    assert runtime_models.get_active_model() == "qwen-plus"
    assert runtime_retrieval.get_settings().candidate_k == 14
