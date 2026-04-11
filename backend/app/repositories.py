from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path
from typing import Iterable

from .models import (
    AgentTask,
    AuthSession,
    Chunk,
    Conversation,
    Document,
    DocumentIndexState,
    DocumentTask,
    Message,
    User,
    UserRole,
    utc_now,
)


class JsonStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, records: list[dict]) -> None:
        self.path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


class ConversationRepository:
    def __init__(self, store: JsonStore | None = None) -> None:
        self._store: OrderedDict[str, Conversation] = OrderedDict()
        self.store = store
        if self.store:
            for record in self.store.load():
                conversation = Conversation.model_validate(record)
                self._store[conversation.id] = conversation

    def create(self, title: str = "???", owner_id: str = "admin") -> Conversation:
        conversation = Conversation(title=title, owner_id=owner_id)
        self._store[conversation.id] = conversation
        self._persist()
        return conversation

    def get(self, conversation_id: str) -> Conversation | None:
        return self._store.get(conversation_id)

    def list(self) -> list[Conversation]:
        return list(self._store.values())

    def list_for_user(self, user_id: str) -> list[Conversation]:
        return [item for item in self._store.values() if item.owner_id == user_id]

    def delete(self, conversation_id: str) -> bool:
        if conversation_id not in self._store:
            return False
        del self._store[conversation_id]
        self._persist()
        return True

    def append_message(self, conversation_id: str, message: Message) -> Conversation:
        conversation = self._store[conversation_id]
        conversation.messages.append(message)
        conversation.updated_at = message.created_at
        self._persist()
        return conversation

    def _persist(self) -> None:
        if self.store:
            self.store.save([item.model_dump(mode="json") for item in self._store.values()])


class DocumentRepository:
    def __init__(self, documents_store: JsonStore | None = None, chunks_store: JsonStore | None = None) -> None:
        self._documents: OrderedDict[str, Document] = OrderedDict()
        self._chunks: OrderedDict[str, Chunk] = OrderedDict()
        self._documents_dirty = False
        self.documents_store = documents_store
        self.chunks_store = chunks_store
        if self.documents_store:
            for record in self.documents_store.load():
                document = Document.model_validate(record)
                self._documents[document.id] = document
        if self.chunks_store:
            for record in self.chunks_store.load():
                chunk = Chunk.model_validate(record)
                self._chunks[chunk.id] = chunk
        self._reconcile_document_index_state()
        if self._documents_dirty:
            self._persist_documents()

    def upsert_document(self, document: Document) -> Document:
        self._documents[document.id] = document
        self._persist_documents()
        return document

    def get_document(self, document_id: str) -> Document | None:
        return self._documents.get(document_id)

    def list_documents(self) -> list[Document]:
        return list(self._documents.values())

    def delete_document(self, document_id: str) -> bool:
        if document_id not in self._documents:
            return False
        del self._documents[document_id]
        for chunk_id, chunk in list(self._chunks.items()):
            if chunk.document_id == document_id:
                del self._chunks[chunk_id]
        self._persist_documents()
        self._persist_chunks()
        return True

    def replace_chunks(self, document_id: str, chunks: Iterable[Chunk]) -> int:
        for chunk_id, chunk in list(self._chunks.items()):
            if chunk.document_id == document_id:
                del self._chunks[chunk_id]
        count = 0
        for chunk in chunks:
            self._chunks[chunk.id] = chunk
            count += 1
        self._persist_chunks()
        return count

    def list_chunks(self) -> list[Chunk]:
        return list(self._chunks.values())

    def list_chunks_for_document(self, document_id: str) -> list[Chunk]:
        return [chunk for chunk in self._chunks.values() if chunk.document_id == document_id]

    def count_chunks_for_document(self, document_id: str) -> int:
        return sum(1 for chunk in self._chunks.values() if chunk.document_id == document_id)

    def count_embedded_chunks_for_document(self, document_id: str) -> int:
        return sum(1 for chunk in self._chunks.values() if chunk.document_id == document_id and chunk.embedding)

    def get_chunk_stats(self) -> dict[str, dict[str, int]]:
        stats: dict[str, dict[str, int]] = {}
        for chunk in self._chunks.values():
            item = stats.setdefault(chunk.document_id, {"chunk_count": 0, "embedded_chunk_count": 0})
            item["chunk_count"] += 1
            if chunk.embedding:
                item["embedded_chunk_count"] += 1
        return stats

    def _reconcile_document_index_state(self) -> None:
        chunk_counts: dict[str, int] = {}
        embedded_chunk_counts: dict[str, int] = {}
        embedding_versions: dict[str, str] = {}
        for chunk in self._chunks.values():
            chunk_counts[chunk.document_id] = chunk_counts.get(chunk.document_id, 0) + 1
            if chunk.embedding:
                embedded_chunk_counts[chunk.document_id] = embedded_chunk_counts.get(chunk.document_id, 0) + 1
                if not chunk.embedding_version:
                    chunk.embedding_version = "legacy"
                if chunk.document_id not in embedding_versions and chunk.embedding_version:
                    embedding_versions[chunk.document_id] = chunk.embedding_version

        for document in self._documents.values():
            chunk_count = chunk_counts.get(document.id, 0)
            normalized_state = self._normalized_index_state(document, chunk_count)
            if normalized_state != document.index_state:
                document.index_state = normalized_state
                if normalized_state == DocumentIndexState.indexed and document.updated_at < (document.indexed_at or document.updated_at):
                    document.updated_at = document.indexed_at or utc_now()
                self._documents_dirty = True
            embedded_chunk_count = embedded_chunk_counts.get(document.id, 0)
            if embedded_chunk_count > 0 and not document.embedding_version:
                document.embedding_version = embedding_versions.get(document.id, "legacy")
                self._documents_dirty = True

    @staticmethod
    def _normalized_index_state(document: Document, chunk_count: int) -> DocumentIndexState:
        if document.index_state == DocumentIndexState.failed:
            return DocumentIndexState.failed
        if chunk_count > 0 and document.indexed_at is not None:
            return DocumentIndexState.indexed
        if chunk_count > 0 and document.index_state == DocumentIndexState.indexing:
            return DocumentIndexState.indexing
        return DocumentIndexState.pending

    def _persist_documents(self) -> None:
        if self.documents_store:
            self.documents_store.save([item.model_dump(mode="json") for item in self._documents.values()])

    def _persist_chunks(self) -> None:
        if self.chunks_store:
            self.chunks_store.save([item.model_dump(mode="json") for item in self._chunks.values()])


class DocumentTaskRepository:
    def __init__(self, store: JsonStore | None = None) -> None:
        self._store: OrderedDict[str, DocumentTask] = OrderedDict()
        self.store = store
        if self.store:
            for record in self.store.load():
                task = DocumentTask.model_validate(record)
                self._store[task.id] = task

    def save(self, task: DocumentTask) -> DocumentTask:
        self._store[task.id] = task
        self._persist()
        return task

    def get(self, task_id: str) -> DocumentTask | None:
        return self._store.get(task_id)

    def list(self) -> list[DocumentTask]:
        return list(self._store.values())

    def list_for_document(self, document_id: str, limit: int | None = None) -> list[DocumentTask]:
        items = [item for item in self._store.values() if item.document_id == document_id]
        items.sort(key=lambda item: item.updated_at, reverse=True)
        if limit is not None and limit >= 0:
            return items[:limit]
        return items

    def _persist(self) -> None:
        if self.store:
            self.store.save([item.model_dump(mode="json") for item in self._store.values()])


class TaskRepository:
    def __init__(self, store: JsonStore | None = None) -> None:
        self._store: OrderedDict[str, AgentTask] = OrderedDict()
        self.store = store
        if self.store:
            for record in self.store.load():
                task = AgentTask.model_validate(record)
                self._store[task.id] = task

    def save(self, task: AgentTask) -> AgentTask:
        self._store[task.id] = task
        self._persist()
        return task

    def get(self, task_id: str) -> AgentTask | None:
        return self._store.get(task_id)

    def list(self) -> list[AgentTask]:
        return list(self._store.values())

    def list_for_user(self, user_id: str) -> list[AgentTask]:
        return [item for item in self._store.values() if item.user_id == user_id]

    def _persist(self) -> None:
        if self.store:
            self.store.save([item.model_dump(mode="json") for item in self._store.values()])


class UserRepository:
    def __init__(self, store: JsonStore | None = None) -> None:
        self._store: OrderedDict[str, User] = OrderedDict()
        self.store = store
        if self.store and self.store.path.exists():
            for record in self.store.load():
                user = User.model_validate(record)
                self._store[user.id] = user
        if not self._store:
            self._seed_defaults()
            self._persist()

    def _seed_defaults(self) -> None:
        for user in (
            User(id="admin", name="admin", role=UserRole.admin),
            User(id="member", name="member", role=UserRole.member),
        ):
            self._store[user.id] = user

    def get(self, user_id: str) -> User | None:
        return self._store.get(user_id)

    def list(self) -> list[User]:
        return list(self._store.values())

    def ensure(self, user_id: str) -> User:
        user = self.get(user_id)
        if user is None:
            raise KeyError(user_id)
        return user

    def _persist(self) -> None:
        if self.store:
            self.store.save([item.model_dump(mode="json") for item in self._store.values()])


class SessionRepository:
    def __init__(self, store: JsonStore | None = None) -> None:
        self._store: OrderedDict[str, AuthSession] = OrderedDict()
        self.store = store
        if self.store and self.store.path.exists():
            for record in self.store.load():
                session = AuthSession.model_validate(record)
                self._store[session.token] = session
        self.delete_expired()

    def save(self, session: AuthSession) -> AuthSession:
        self.delete_expired()
        self._store[session.token] = session
        self._persist()
        return session

    def get(self, token: str) -> AuthSession | None:
        session = self._store.get(token)
        if session is None:
            return None
        if session.expires_at <= utc_now():
            del self._store[token]
            self._persist()
            return None
        return session

    def delete(self, token: str) -> bool:
        if token not in self._store:
            return False
        del self._store[token]
        self._persist()
        return True

    def delete_expired(self) -> int:
        now = utc_now()
        expired_tokens = [token for token, session in self._store.items() if session.expires_at <= now]
        for token in expired_tokens:
            del self._store[token]
        if expired_tokens:
            self._persist()
        return len(expired_tokens)

    def _persist(self) -> None:
        if self.store:
            self.store.save([item.model_dump(mode="json") for item in self._store.values()])
