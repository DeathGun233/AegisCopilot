from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from app.models import AgentTask, AuthSession, Chunk, Conversation, Document, DocumentTask, User
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


def migrate_runtime_settings(storage_dir: Path, database_url: str) -> int:
    database = SqlDatabase(database_url)
    runtime_repo = SqlRuntimeSettingsRepository(database)

    runtime_model = _read_json(storage_dir / "runtime_model.json")
    if isinstance(runtime_model, dict) and runtime_model:
        runtime_repo.set("runtime_model", runtime_model)

    runtime_retrieval = _read_json(storage_dir / "runtime_retrieval.json")
    if isinstance(runtime_retrieval, dict) and runtime_retrieval:
        runtime_repo.set("runtime_retrieval", runtime_retrieval)

    return 0


def migrate_core_records(storage_dir: Path, database_url: str) -> int:
    database = SqlDatabase(database_url)
    conversations = SqlConversationRepository(database)
    documents = SqlDocumentRepository(database)
    document_tasks = SqlDocumentTaskRepository(database)
    tasks = SqlTaskRepository(database)
    users = SqlUserRepository(database)
    sessions = SqlSessionRepository(database)

    for conversation in _load_records(storage_dir / "conversations.json", Conversation):
        conversations.save(conversation)

    for document in _load_records(storage_dir / "documents.json", Document):
        documents.upsert_document(document)

    chunks_by_document: dict[str, list[Chunk]] = {}
    for chunk in _load_records(storage_dir / "chunks.json", Chunk):
        chunks_by_document.setdefault(chunk.document_id, []).append(chunk)
    for document_id, chunks in chunks_by_document.items():
        documents.replace_chunks(document_id, chunks)

    for task in _load_records(storage_dir / "document_tasks.json", DocumentTask):
        document_tasks.save(task)

    for task in _load_records(storage_dir / "tasks.json", AgentTask):
        tasks.save(task)

    for user in _load_records(storage_dir / "users.json", User):
        users.save(user)

    for session in _load_records(storage_dir / "sessions.json", AuthSession):
        sessions.save(session)

    return 0


def migrate_all(storage_dir: Path, database_url: str) -> int:
    migrate_core_records(storage_dir, database_url)
    migrate_runtime_settings(storage_dir, database_url)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migrate JSON runtime settings into the SQL backend.")
    parser.add_argument("--storage-dir", type=Path, default=ROOT / "backend" / "storage")
    parser.add_argument("--database-url", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return migrate_all(args.storage_dir, args.database_url)


if __name__ == "__main__":
    raise SystemExit(main())
