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


def test_migration_dry_run_writes_report_without_touching_database(tmp_path: Path) -> None:
    module = _load_module()
    from app.models import Conversation, Message, MessageRole, utc_now

    storage_dir = tmp_path / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)
    now = utc_now()
    conversation = Conversation(
        id="conv-dry-run",
        owner_id="admin",
        title="Dry Run Conversation",
        messages=[Message(id="msg-dry-run", role=MessageRole.user, content="hello", created_at=now)],
        created_at=now,
        updated_at=now,
    )
    _dump_models(storage_dir / "conversations.json", [conversation])

    database_path = tmp_path / "dry-run.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    report_path = tmp_path / "migration-report.json"

    assert module.main(
        [
            "--storage-dir",
            str(storage_dir),
            "--database-url",
            database_url,
            "--dry-run",
            "--report-path",
            str(report_path),
        ]
    ) == 0

    assert not database_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["dry_run"] is True
    assert report["counts"]["conversations"] == 1
    assert report["counts"]["documents"] == 0


def test_migration_writes_report_and_rollback_sql(tmp_path: Path) -> None:
    module = _load_module()
    from app.models import (
        Chunk,
        Conversation,
        Document,
        DocumentIndexState,
        Message,
        MessageRole,
        User,
        UserRole,
        utc_now,
    )

    storage_dir = tmp_path / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)
    now = utc_now()
    conversation = Conversation(
        id="conv-report",
        owner_id="admin",
        title="Report Conversation",
        messages=[Message(id="msg-report", role=MessageRole.user, content="hello", created_at=now)],
        created_at=now,
        updated_at=now,
    )
    document = Document(
        id="doc-report",
        title="Report Document",
        source_type="text",
        department="ops",
        version="v1",
        content="Report content",
        tags=["report"],
        created_at=now,
        updated_at=now,
        indexed_at=now,
        index_state=DocumentIndexState.indexed,
        embedding_version="test-v1",
    )
    chunk = Chunk(
        id="chunk-report",
        document_id=document.id,
        document_title=document.title,
        text=document.content,
        chunk_index=0,
        tokens=["report"],
        embedding=[0.1],
        embedding_version="test-v1",
        metadata={"department": "ops"},
    )
    user = User(id="auditor", name="Auditor", role=UserRole.member, created_at=now)

    _dump_models(storage_dir / "conversations.json", [conversation])
    _dump_models(storage_dir / "documents.json", [document])
    _dump_models(storage_dir / "chunks.json", [chunk])
    _dump_models(storage_dir / "users.json", [user])
    (storage_dir / "runtime_model.json").write_text(
        json.dumps({"active_model": "qwen-plus"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    database_url = f"sqlite:///{(tmp_path / 'reported.db').as_posix()}"
    report_path = tmp_path / "migration-report.json"
    rollback_sql_path = tmp_path / "rollback.sql"

    assert module.main(
        [
            "--storage-dir",
            str(storage_dir),
            "--database-url",
            database_url,
            "--report-path",
            str(report_path),
            "--rollback-sql-path",
            str(rollback_sql_path),
        ]
    ) == 0

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["dry_run"] is False
    assert report["counts"]["conversations"] == 1
    assert report["counts"]["documents"] == 1
    assert report["counts"]["chunks"] == 1
    assert report["counts"]["runtime_model"] == 1

    rollback_sql = rollback_sql_path.read_text(encoding="utf-8")
    assert "DELETE FROM conversations WHERE id IN ('conv-report');" in rollback_sql
    assert "DELETE FROM chunks WHERE id IN ('chunk-report');" in rollback_sql
    assert "DELETE FROM runtime_settings WHERE key IN ('runtime_model');" in rollback_sql


def test_migration_skips_legacy_or_expired_sessions_in_report_and_database(tmp_path: Path) -> None:
    module = _load_module()
    from app.models import AuthSession, utc_now
    from app.sql_repositories import SqlDatabase, SqlSessionRepository

    storage_dir = tmp_path / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)
    now = utc_now()
    valid_session = AuthSession(
        token="session-valid",
        user_id="admin",
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=4),
    )
    expired_session = AuthSession(
        token="session-expired",
        user_id="admin",
        created_at=now - timedelta(days=2),
        last_seen_at=now - timedelta(days=2),
        expires_at=now - timedelta(days=1),
    )
    legacy_session = {
        "token": "session-legacy",
        "user_id": "admin",
        "created_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
    }
    (storage_dir / "sessions.json").write_text(
        json.dumps(
            [
                valid_session.model_dump(mode="json"),
                expired_session.model_dump(mode="json"),
                legacy_session,
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    database_url = f"sqlite:///{(tmp_path / 'sessions.db').as_posix()}"
    report_path = tmp_path / "migration-report.json"

    assert module.main(
        [
            "--storage-dir",
            str(storage_dir),
            "--database-url",
            database_url,
            "--report-path",
            str(report_path),
        ]
    ) == 0

    report = json.loads(report_path.read_text(encoding="utf-8"))
    sessions = SqlSessionRepository(SqlDatabase(database_url))

    assert report["counts"]["sessions"] == 1
    assert sessions.get(valid_session.token) is not None
    assert sessions.get(expired_session.token) is None
    assert sessions.get("session-legacy") is None


def test_sql_session_repository_deletes_expired_session_without_recursion(tmp_path: Path) -> None:
    from app.models import AuthSession, utc_now
    from app.sql_repositories import SqlDatabase, SqlSessionRepository

    database_url = f"sqlite:///{(tmp_path / 'expired-session.db').as_posix()}"
    sessions = SqlSessionRepository(SqlDatabase(database_url))
    now = utc_now()
    expired_session = AuthSession(
        token="expired-token",
        user_id="admin",
        created_at=now - timedelta(hours=2),
        last_seen_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
    )
    sessions.save(expired_session)

    assert sessions.get(expired_session.token) is None
    assert sessions.delete(expired_session.token) is False


def test_alembic_initial_migration_covers_sql_persistence_tables() -> None:
    migration_path = ROOT / "backend" / "alembic" / "versions" / "0001_initial_sql_persistence.py"
    content = migration_path.read_text(encoding="utf-8")

    for table_name in (
        "conversations",
        "documents",
        "chunks",
        "document_tasks",
        "tasks",
        "users",
        "sessions",
        "runtime_settings",
    ):
        assert table_name in content


def test_sqlite_url_preserves_posix_absolute_paths() -> None:
    from app.sql_repositories import SqlDatabase

    assert SqlDatabase._resolve_sqlite_path("sqlite:////tmp/aegiscopilot.db") == "/tmp/aegiscopilot.db"


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
