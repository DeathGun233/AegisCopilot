from __future__ import annotations

import json
import sqlite3
from typing import Iterable
from urllib.parse import urlparse

from .models import (
    AgentTask,
    AuthSession,
    Chunk,
    Conversation,
    Document,
    DocumentTask,
    Message,
    User,
    UserRole,
    utc_now,
)


def _serialize_model(model) -> str:
    return json.dumps(model.model_dump(mode="json"), ensure_ascii=False)


def _deserialize_model(model_type, payload: str):
    return model_type.model_validate(json.loads(payload))


class SqlDatabase:
    def __init__(self, url: str) -> None:
        self.url = url
        self.kind = self._detect_kind(url)
        self.param = "?" if self.kind == "sqlite" else "%s"
        self._sqlite_path = self._resolve_sqlite_path(url) if self.kind == "sqlite" else ""
        self._init_schema()

    @staticmethod
    def _detect_kind(url: str) -> str:
        normalized = url.strip().lower()
        if normalized.startswith("sqlite:///"):
            return "sqlite"
        if normalized.startswith("postgresql://") or normalized.startswith("postgresql+psycopg://"):
            return "postgres"
        raise ValueError(f"Unsupported database URL: {url}")

    @staticmethod
    def _resolve_sqlite_path(url: str) -> str:
        parsed = urlparse(url)
        if parsed.netloc:
            return f"//{parsed.netloc}{parsed.path}"
        if parsed.path.startswith("//"):
            return parsed.path[1:]
        if len(parsed.path) >= 3 and parsed.path[0] == "/" and parsed.path[2] == ":":
            return parsed.path[1:]
        return parsed.path.lstrip("/")

    def _connect(self):
        if self.kind == "sqlite":
            connection = sqlite3.connect(self._sqlite_path, check_same_thread=False)
            connection.row_factory = sqlite3.Row
            return connection
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("Postgres support requires psycopg to be installed.") from exc
        return psycopg.connect(self.url.replace("postgresql+psycopg://", "postgresql://"), row_factory=dict_row)

    def _sql(self, statement: str) -> str:
        return statement if self.kind == "sqlite" else statement.replace("?", "%s")

    def execute(self, statement: str, params: tuple = (), *, fetch: str = "none"):
        sql = self._sql(statement)
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(sql, params)
            if fetch == "one":
                row = cursor.fetchone()
            elif fetch == "all":
                row = cursor.fetchall()
            else:
                row = None
            connection.commit()
        return row

    def executemany(self, statement: str, params: list[tuple]) -> None:
        if not params:
            return
        sql = self._sql(statement)
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.executemany(sql, params)
            connection.commit()

    def _init_schema(self) -> None:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS conversations (
              id TEXT PRIMARY KEY,
              owner_id TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              payload TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_conversations_owner_id ON conversations (owner_id)",
            """
            CREATE TABLE IF NOT EXISTS documents (
              id TEXT PRIMARY KEY,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              index_state TEXT NOT NULL,
              payload TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS chunks (
              id TEXT PRIMARY KEY,
              document_id TEXT NOT NULL,
              chunk_index INTEGER NOT NULL,
              has_embedding INTEGER NOT NULL,
              embedding_version TEXT NOT NULL,
              payload TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks (document_id)",
            """
            CREATE TABLE IF NOT EXISTS document_tasks (
              id TEXT PRIMARY KEY,
              document_id TEXT,
              updated_at TEXT NOT NULL,
              payload TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_document_tasks_document_id ON document_tasks (document_id)",
            """
            CREATE TABLE IF NOT EXISTS tasks (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              created_at TEXT NOT NULL,
              payload TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks (user_id)",
            """
            CREATE TABLE IF NOT EXISTS users (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              role TEXT NOT NULL,
              created_at TEXT NOT NULL,
              payload TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS sessions (
              token TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              payload TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions (user_id)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions (expires_at)",
            """
            CREATE TABLE IF NOT EXISTS runtime_settings (
              key TEXT PRIMARY KEY,
              payload TEXT NOT NULL
            )
            """,
        ]
        for statement in statements:
            self.execute(statement)


class SqlConversationRepository:
    def __init__(self, db: SqlDatabase) -> None:
        self.db = db

    def create(self, title: str = "新对话", owner_id: str = "admin") -> Conversation:
        conversation = Conversation(title=title, owner_id=owner_id)
        self.save(conversation)
        return conversation

    def save(self, conversation: Conversation) -> Conversation:
        self._save(conversation)
        return conversation

    def get(self, conversation_id: str) -> Conversation | None:
        row = self.db.execute(
            "SELECT payload FROM conversations WHERE id = ?",
            (conversation_id,),
            fetch="one",
        )
        if row is None:
            return None
        return _deserialize_model(Conversation, row["payload"] if hasattr(row, "keys") else row[0])

    def list(self) -> list[Conversation]:
        rows = self.db.execute(
            "SELECT payload FROM conversations ORDER BY created_at ASC",
            fetch="all",
        )
        return [_deserialize_model(Conversation, row["payload"] if hasattr(row, "keys") else row[0]) for row in rows]

    def list_for_user(self, user_id: str) -> list[Conversation]:
        rows = self.db.execute(
            "SELECT payload FROM conversations WHERE owner_id = ? ORDER BY created_at ASC",
            (user_id,),
            fetch="all",
        )
        return [_deserialize_model(Conversation, row["payload"] if hasattr(row, "keys") else row[0]) for row in rows]

    def delete(self, conversation_id: str) -> bool:
        existing = self.get(conversation_id)
        if existing is None:
            return False
        self.db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        return True

    def append_message(self, conversation_id: str, message: Message) -> Conversation:
        conversation = self.get(conversation_id)
        if conversation is None:
            raise KeyError(conversation_id)
        conversation.messages.append(message)
        conversation.updated_at = message.created_at
        self._save(conversation)
        return conversation

    def _save(self, conversation: Conversation) -> None:
        self.db.execute("DELETE FROM conversations WHERE id = ?", (conversation.id,))
        self.db.execute(
            """
            INSERT INTO conversations (id, owner_id, created_at, updated_at, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                conversation.id,
                conversation.owner_id,
                conversation.created_at.isoformat(),
                conversation.updated_at.isoformat(),
                _serialize_model(conversation),
            ),
        )


class SqlDocumentRepository:
    def __init__(self, db: SqlDatabase) -> None:
        self.db = db

    def upsert_document(self, document: Document) -> Document:
        self.db.execute("DELETE FROM documents WHERE id = ?", (document.id,))
        self.db.execute(
            """
            INSERT INTO documents (id, created_at, updated_at, index_state, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                document.id,
                document.created_at.isoformat(),
                document.updated_at.isoformat(),
                document.index_state.value,
                _serialize_model(document),
            ),
        )
        return document

    def get_document(self, document_id: str) -> Document | None:
        row = self.db.execute(
            "SELECT payload FROM documents WHERE id = ?",
            (document_id,),
            fetch="one",
        )
        if row is None:
            return None
        return _deserialize_model(Document, row["payload"] if hasattr(row, "keys") else row[0])

    def list_documents(self) -> list[Document]:
        rows = self.db.execute(
            "SELECT payload FROM documents ORDER BY created_at ASC",
            fetch="all",
        )
        return [_deserialize_model(Document, row["payload"] if hasattr(row, "keys") else row[0]) for row in rows]

    def delete_document(self, document_id: str) -> bool:
        existing = self.get_document(document_id)
        if existing is None:
            return False
        self.db.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        self.db.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
        return True

    def replace_chunks(self, document_id: str, chunks: Iterable[Chunk]) -> int:
        items = list(chunks)
        self.db.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
        self.db.executemany(
            """
            INSERT INTO chunks (id, document_id, chunk_index, has_embedding, embedding_version, payload)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    chunk.id,
                    chunk.document_id,
                    chunk.chunk_index,
                    1 if chunk.embedding else 0,
                    chunk.embedding_version,
                    _serialize_model(chunk),
                )
                for chunk in items
            ],
        )
        return len(items)

    def list_chunks(self) -> list[Chunk]:
        rows = self.db.execute(
            "SELECT payload FROM chunks ORDER BY document_id ASC, chunk_index ASC",
            fetch="all",
        )
        return [_deserialize_model(Chunk, row["payload"] if hasattr(row, "keys") else row[0]) for row in rows]

    def list_chunks_for_document(self, document_id: str) -> list[Chunk]:
        rows = self.db.execute(
            "SELECT payload FROM chunks WHERE document_id = ? ORDER BY chunk_index ASC",
            (document_id,),
            fetch="all",
        )
        return [_deserialize_model(Chunk, row["payload"] if hasattr(row, "keys") else row[0]) for row in rows]

    def count_chunks_for_document(self, document_id: str) -> int:
        row = self.db.execute(
            "SELECT COUNT(*) AS count FROM chunks WHERE document_id = ?",
            (document_id,),
            fetch="one",
        )
        return int(row["count"] if hasattr(row, "keys") else row[0])

    def count_embedded_chunks_for_document(self, document_id: str) -> int:
        row = self.db.execute(
            "SELECT COUNT(*) AS count FROM chunks WHERE document_id = ? AND has_embedding = 1",
            (document_id,),
            fetch="one",
        )
        return int(row["count"] if hasattr(row, "keys") else row[0])

    def get_chunk_stats(self) -> dict[str, dict[str, int]]:
        rows = self.db.execute(
            "SELECT document_id, has_embedding FROM chunks ORDER BY document_id ASC, chunk_index ASC",
            fetch="all",
        )
        stats: dict[str, dict[str, int]] = {}
        for row in rows:
            document_id = row["document_id"] if hasattr(row, "keys") else row[0]
            has_embedding = row["has_embedding"] if hasattr(row, "keys") else row[1]
            item = stats.setdefault(document_id, {"chunk_count": 0, "embedded_chunk_count": 0})
            item["chunk_count"] += 1
            if has_embedding:
                item["embedded_chunk_count"] += 1
        return stats


class SqlDocumentTaskRepository:
    def __init__(self, db: SqlDatabase) -> None:
        self.db = db

    def save(self, task: DocumentTask) -> DocumentTask:
        self.db.execute("DELETE FROM document_tasks WHERE id = ?", (task.id,))
        self.db.execute(
            """
            INSERT INTO document_tasks (id, document_id, updated_at, payload)
            VALUES (?, ?, ?, ?)
            """,
            (
                task.id,
                task.document_id,
                task.updated_at.isoformat(),
                _serialize_model(task),
            ),
        )
        return task

    def get(self, task_id: str) -> DocumentTask | None:
        row = self.db.execute(
            "SELECT payload FROM document_tasks WHERE id = ?",
            (task_id,),
            fetch="one",
        )
        if row is None:
            return None
        return _deserialize_model(DocumentTask, row["payload"] if hasattr(row, "keys") else row[0])

    def list(self) -> list[DocumentTask]:
        rows = self.db.execute(
            "SELECT payload FROM document_tasks ORDER BY updated_at DESC",
            fetch="all",
        )
        return [_deserialize_model(DocumentTask, row["payload"] if hasattr(row, "keys") else row[0]) for row in rows]

    def list_for_document(self, document_id: str, limit: int | None = None) -> list[DocumentTask]:
        statement = "SELECT payload FROM document_tasks WHERE document_id = ? ORDER BY updated_at DESC"
        params: tuple = (document_id,)
        if limit is not None and limit >= 0:
            statement += " LIMIT ?"
            params = (document_id, limit)
        rows = self.db.execute(statement, params, fetch="all")
        return [_deserialize_model(DocumentTask, row["payload"] if hasattr(row, "keys") else row[0]) for row in rows]


class SqlTaskRepository:
    def __init__(self, db: SqlDatabase) -> None:
        self.db = db

    def save(self, task: AgentTask) -> AgentTask:
        self.db.execute("DELETE FROM tasks WHERE id = ?", (task.id,))
        self.db.execute(
            """
            INSERT INTO tasks (id, user_id, created_at, payload)
            VALUES (?, ?, ?, ?)
            """,
            (
                task.id,
                task.user_id,
                task.created_at.isoformat(),
                _serialize_model(task),
            ),
        )
        return task

    def get(self, task_id: str) -> AgentTask | None:
        row = self.db.execute(
            "SELECT payload FROM tasks WHERE id = ?",
            (task_id,),
            fetch="one",
        )
        if row is None:
            return None
        return _deserialize_model(AgentTask, row["payload"] if hasattr(row, "keys") else row[0])

    def list(self) -> list[AgentTask]:
        rows = self.db.execute(
            "SELECT payload FROM tasks ORDER BY created_at ASC",
            fetch="all",
        )
        return [_deserialize_model(AgentTask, row["payload"] if hasattr(row, "keys") else row[0]) for row in rows]

    def list_for_user(self, user_id: str) -> list[AgentTask]:
        rows = self.db.execute(
            "SELECT payload FROM tasks WHERE user_id = ? ORDER BY created_at ASC",
            (user_id,),
            fetch="all",
        )
        return [_deserialize_model(AgentTask, row["payload"] if hasattr(row, "keys") else row[0]) for row in rows]


class SqlUserRepository:
    def __init__(self, db: SqlDatabase) -> None:
        self.db = db
        if not self.list():
            self._seed_defaults()

    def _seed_defaults(self) -> None:
        for user in (
            User(id="admin", name="admin", role=UserRole.admin),
            User(id="member", name="member", role=UserRole.member),
        ):
            self.save(user)

    def get(self, user_id: str) -> User | None:
        row = self.db.execute(
            "SELECT payload FROM users WHERE id = ?",
            (user_id,),
            fetch="one",
        )
        if row is None:
            return None
        return _deserialize_model(User, row["payload"] if hasattr(row, "keys") else row[0])

    def list(self) -> list[User]:
        rows = self.db.execute(
            "SELECT payload FROM users ORDER BY created_at ASC",
            fetch="all",
        )
        return [_deserialize_model(User, row["payload"] if hasattr(row, "keys") else row[0]) for row in rows]

    def ensure(self, user_id: str) -> User:
        user = self.get(user_id)
        if user is None:
            raise KeyError(user_id)
        return user

    def save(self, user: User) -> User:
        self._save(user)
        return user

    def _save(self, user: User) -> None:
        self.db.execute("DELETE FROM users WHERE id = ?", (user.id,))
        self.db.execute(
            """
            INSERT INTO users (id, name, role, created_at, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user.id,
                user.name,
                user.role.value,
                user.created_at.isoformat(),
                _serialize_model(user),
            ),
        )


class SqlSessionRepository:
    def __init__(self, db: SqlDatabase) -> None:
        self.db = db
        self.delete_expired()

    def save(self, session: AuthSession) -> AuthSession:
        self.delete_expired()
        self.db.execute("DELETE FROM sessions WHERE token = ?", (session.token,))
        self.db.execute(
            """
            INSERT INTO sessions (token, user_id, expires_at, payload)
            VALUES (?, ?, ?, ?)
            """,
            (
                session.token,
                session.user_id,
                session.expires_at.isoformat(),
                _serialize_model(session),
            ),
        )
        return session

    def get(self, token: str) -> AuthSession | None:
        row = self.db.execute(
            "SELECT payload FROM sessions WHERE token = ?",
            (token,),
            fetch="one",
        )
        if row is None:
            return None
        session = _deserialize_model(AuthSession, row["payload"] if hasattr(row, "keys") else row[0])
        if session.expires_at <= utc_now():
            self.delete(token)
            return None
        return session

    def delete(self, token: str) -> bool:
        row = self.db.execute(
            "SELECT token FROM sessions WHERE token = ?",
            (token,),
            fetch="one",
        )
        if row is None:
            return False
        self.db.execute("DELETE FROM sessions WHERE token = ?", (token,))
        return True

    def delete_expired(self) -> int:
        now = utc_now().isoformat()
        rows = self.db.execute(
            "SELECT token FROM sessions WHERE expires_at <= ?",
            (now,),
            fetch="all",
        )
        self.db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        return len(rows)


class SqlRuntimeSettingsRepository:
    def __init__(self, db: SqlDatabase) -> None:
        self.db = db

    def get(self, key: str) -> dict[str, object]:
        row = self.db.execute(
            "SELECT payload FROM runtime_settings WHERE key = ?",
            (key,),
            fetch="one",
        )
        if row is None:
            return {}
        payload = row["payload"] if hasattr(row, "keys") else row[0]
        return json.loads(payload)

    def set(self, key: str, payload: dict[str, object]) -> None:
        self.db.execute("DELETE FROM runtime_settings WHERE key = ?", (key,))
        self.db.execute(
            "INSERT INTO runtime_settings (key, payload) VALUES (?, ?)",
            (key, json.dumps(payload, ensure_ascii=False, indent=2)),
        )
