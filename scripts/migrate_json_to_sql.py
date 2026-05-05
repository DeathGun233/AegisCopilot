from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from app.models import AgentTask, AuthSession, Chunk, Conversation, Document, DocumentTask, User
from app.services.chunk_hierarchy import assign_chunk_hierarchy
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


@dataclass(frozen=True)
class MigrationPayload:
    conversations: list[Conversation]
    documents: list[Document]
    chunks: list[Chunk]
    document_tasks: list[DocumentTask]
    tasks: list[AgentTask]
    users: list[User]
    sessions: list[AuthSession]
    runtime_model: dict | None
    runtime_retrieval: dict | None

    def counts(self) -> dict[str, int]:
        return {
            "conversations": len(self.conversations),
            "documents": len(self.documents),
            "chunks": len(self.chunks),
            "document_tasks": len(self.document_tasks),
            "tasks": len(self.tasks),
            "users": len(self.users),
            "sessions": len(self.sessions),
            "runtime_model": 1 if self.runtime_model else 0,
            "runtime_retrieval": 1 if self.runtime_retrieval else 0,
        }


def _read_json(path: Path) -> object:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _load_records(path: Path, model_type) -> list:
    payload = _read_json(path)
    if not isinstance(payload, list):
        return []
    return [model_type.model_validate(item) for item in payload]


def _load_sessions(path: Path) -> list[AuthSession]:
    payload = _read_json(path)
    if not isinstance(payload, list):
        return []
    now = datetime.now(timezone.utc)
    sessions: list[AuthSession] = []
    for item in payload:
        if not isinstance(item, dict) or not item.get("expires_at"):
            continue
        session = AuthSession.model_validate(item)
        if session.expires_at > now:
            sessions.append(session)
    return sessions


def _load_payload(storage_dir: Path) -> MigrationPayload:
    runtime_model = _read_json(storage_dir / "runtime_model.json")
    runtime_retrieval = _read_json(storage_dir / "runtime_retrieval.json")
    chunks = _load_records(storage_dir / "chunks.json", Chunk)
    chunks_by_document: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        chunks_by_document.setdefault(chunk.document_id, []).append(chunk)
    normalized_chunks: list[Chunk] = []
    for document_chunks in chunks_by_document.values():
        normalized_chunks.extend(assign_chunk_hierarchy(sorted(document_chunks, key=lambda item: item.chunk_index)))
    return MigrationPayload(
        conversations=_load_records(storage_dir / "conversations.json", Conversation),
        documents=_load_records(storage_dir / "documents.json", Document),
        chunks=normalized_chunks,
        document_tasks=_load_records(storage_dir / "document_tasks.json", DocumentTask),
        tasks=_load_records(storage_dir / "tasks.json", AgentTask),
        users=_load_records(storage_dir / "users.json", User),
        sessions=_load_sessions(storage_dir / "sessions.json"),
        runtime_model=runtime_model if isinstance(runtime_model, dict) and runtime_model else None,
        runtime_retrieval=runtime_retrieval if isinstance(runtime_retrieval, dict) and runtime_retrieval else None,
    )


def _quote_sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _delete_statement(table: str, column: str, values: list[str]) -> str | None:
    unique_values = sorted(set(values))
    if not unique_values:
        return None
    quoted_values = ", ".join(_quote_sql_literal(value) for value in unique_values)
    return f"DELETE FROM {table} WHERE {column} IN ({quoted_values});"


def build_rollback_sql(payload: MigrationPayload) -> str:
    statements = [
        _delete_statement("runtime_settings", "key", ["runtime_model"] if payload.runtime_model else []),
        _delete_statement("runtime_settings", "key", ["runtime_retrieval"] if payload.runtime_retrieval else []),
        _delete_statement("sessions", "token", [session.token for session in payload.sessions]),
        _delete_statement("tasks", "id", [task.id for task in payload.tasks]),
        _delete_statement("document_tasks", "id", [task.id for task in payload.document_tasks]),
        _delete_statement("chunks", "id", [chunk.id for chunk in payload.chunks]),
        _delete_statement("documents", "id", [document.id for document in payload.documents]),
        _delete_statement("conversations", "id", [conversation.id for conversation in payload.conversations]),
        _delete_statement("users", "id", [user.id for user in payload.users]),
    ]
    rendered = [statement for statement in statements if statement is not None]
    if not rendered:
        return "-- No migrated rows detected.\n"
    return "\n".join(rendered) + "\n"


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_report(path: Path, *, storage_dir: Path, database_url: str, dry_run: bool, payload: MigrationPayload) -> None:
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "storage_dir": str(storage_dir),
        "database_url": database_url,
        "dry_run": dry_run,
        "counts": payload.counts(),
    }
    _write_text(path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")


def _print_counts(payload: MigrationPayload) -> None:
    print("Migration counts:")
    for key, value in payload.counts().items():
        print(f"- {key}: {value}")


def _migrate_runtime_settings(payload: MigrationPayload, database: SqlDatabase) -> None:
    runtime_repo = SqlRuntimeSettingsRepository(database)

    if payload.runtime_model:
        runtime_repo.set("runtime_model", payload.runtime_model)

    if payload.runtime_retrieval:
        runtime_repo.set("runtime_retrieval", payload.runtime_retrieval)


def migrate_runtime_settings(storage_dir: Path, database_url: str) -> int:
    payload = _load_payload(storage_dir)
    database = SqlDatabase(database_url)
    _migrate_runtime_settings(payload, database)
    return 0


def _migrate_core_records(payload: MigrationPayload, database: SqlDatabase) -> None:
    conversations = SqlConversationRepository(database)
    documents = SqlDocumentRepository(database)
    document_tasks = SqlDocumentTaskRepository(database)
    tasks = SqlTaskRepository(database)
    users = SqlUserRepository(database)
    sessions = SqlSessionRepository(database)

    for conversation in payload.conversations:
        conversations.save(conversation)

    for document in payload.documents:
        documents.upsert_document(document)

    chunks_by_document: dict[str, list[Chunk]] = {}
    for chunk in payload.chunks:
        chunks_by_document.setdefault(chunk.document_id, []).append(chunk)
    for document_id, chunks in chunks_by_document.items():
        documents.replace_chunks(document_id, chunks)

    for task in payload.document_tasks:
        document_tasks.save(task)

    for task in payload.tasks:
        tasks.save(task)

    for user in payload.users:
        users.save(user)

    for session in payload.sessions:
        sessions.save(session)


def migrate_core_records(storage_dir: Path, database_url: str) -> int:
    payload = _load_payload(storage_dir)
    database = SqlDatabase(database_url)
    _migrate_core_records(payload, database)

    return 0


def migrate_all(
    storage_dir: Path,
    database_url: str,
    *,
    dry_run: bool = False,
    report_path: Path | None = None,
    rollback_sql_path: Path | None = None,
) -> int:
    payload = _load_payload(storage_dir)
    _print_counts(payload)

    if report_path is not None:
        _write_report(report_path, storage_dir=storage_dir, database_url=database_url, dry_run=dry_run, payload=payload)

    if rollback_sql_path is not None:
        _write_text(rollback_sql_path, build_rollback_sql(payload))

    if dry_run:
        return 0

    database = SqlDatabase(database_url)
    _migrate_core_records(payload, database)
    _migrate_runtime_settings(payload, database)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migrate JSON storage into the SQL backend.")
    parser.add_argument("--storage-dir", type=Path, default=ROOT / "backend" / "storage")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report-path", type=Path)
    parser.add_argument("--rollback-sql-path", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return migrate_all(
        args.storage_dir,
        args.database_url,
        dry_run=args.dry_run,
        report_path=args.report_path,
        rollback_sql_path=args.rollback_sql_path,
    )


if __name__ == "__main__":
    raise SystemExit(main())
