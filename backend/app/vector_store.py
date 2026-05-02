from __future__ import annotations

import importlib
import json
from collections.abc import Iterable
from typing import Any, Protocol

from .models import Chunk
from .repositories import DocumentRepository


class VectorStore(Protocol):
    def replace_document_chunks(self, document_id: str, chunks: Iterable[Chunk]) -> int:
        ...

    def delete_document(self, document_id: str) -> bool:
        ...

    def search_candidates(self, query: str, query_embedding: list[float], limit: int) -> list[Chunk]:
        ...

    def list_chunks(self) -> list[Chunk]:
        ...

    def list_chunks_for_document(self, document_id: str) -> list[Chunk]:
        ...

    def count_chunks_for_document(self, document_id: str) -> int:
        ...

    def count_embedded_chunks_for_document(self, document_id: str) -> int:
        ...

    def get_chunk_stats(self) -> dict[str, dict[str, int]]:
        ...


class LocalVectorStore:
    def __init__(self, repository: DocumentRepository) -> None:
        self.repository = repository

    def replace_document_chunks(self, document_id: str, chunks: Iterable[Chunk]) -> int:
        return self.repository.replace_chunks(document_id, chunks)

    def delete_document(self, document_id: str) -> bool:
        existing_count = self.repository.count_chunks_for_document(document_id)
        self.repository.replace_chunks(document_id, [])
        return existing_count > 0

    def search_candidates(self, query: str, query_embedding: list[float], limit: int) -> list[Chunk]:
        return self.repository.list_chunks()

    def list_chunks(self) -> list[Chunk]:
        return self.repository.list_chunks()

    def list_chunks_for_document(self, document_id: str) -> list[Chunk]:
        return self.repository.list_chunks_for_document(document_id)

    def count_chunks_for_document(self, document_id: str) -> int:
        return self.repository.count_chunks_for_document(document_id)

    def count_embedded_chunks_for_document(self, document_id: str) -> int:
        return self.repository.count_embedded_chunks_for_document(document_id)

    def get_chunk_stats(self) -> dict[str, dict[str, int]]:
        return self.repository.get_chunk_stats()


class MilvusVectorStore:
    output_fields = [
        "id",
        "document_id",
        "document_title",
        "text",
        "chunk_index",
        "tokens_json",
        "embedding",
        "embedding_version",
        "metadata_json",
    ]

    def __init__(
        self,
        *,
        uri: str,
        token: str,
        collection: str,
        dimension: int,
        query_limit: int = 16384,
    ) -> None:
        self.uri = uri
        self.token = token
        self.collection = collection
        self.dimension = dimension
        self.query_limit = query_limit
        pymilvus = self._load_pymilvus()
        self._data_type = getattr(pymilvus, "DataType", None)
        client_options: dict[str, object] = {"uri": uri}
        if token:
            client_options["token"] = token
        self.client = pymilvus.MilvusClient(**client_options)
        self._ensure_collection()

    @staticmethod
    def _load_pymilvus():
        try:
            return importlib.import_module("pymilvus")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Milvus vector store requires pymilvus. "
                "Install it with `pip install -e \".[milvus]\"` or use "
                "`AEGIS_VECTOR_STORE_PROVIDER=local`."
            ) from exc

    def _ensure_collection(self) -> None:
        if self.client.has_collection(collection_name=self.collection):
            return
        id_type = getattr(self._data_type, "VARCHAR", "VARCHAR")
        self.client.create_collection(
            collection_name=self.collection,
            dimension=self.dimension,
            primary_field_name="id",
            id_type=id_type,
            vector_field_name="embedding",
            metric_type="COSINE",
            auto_id=False,
            max_length=128,
        )

    def replace_document_chunks(self, document_id: str, chunks: Iterable[Chunk]) -> int:
        chunk_list = list(chunks)
        self.client.delete(
            collection_name=self.collection,
            filter=self._document_filter(document_id),
        )
        if not chunk_list:
            return 0
        records = [self._chunk_to_record(chunk) for chunk in chunk_list]
        self.client.insert(collection_name=self.collection, data=records)
        return len(records)

    def delete_document(self, document_id: str) -> bool:
        result = self.client.delete(
            collection_name=self.collection,
            filter=self._document_filter(document_id),
        )
        return self._mutation_count(result) > 0

    def search_candidates(self, query: str, query_embedding: list[float], limit: int) -> list[Chunk]:
        if limit <= 0:
            return []
        if not query_embedding:
            return self.list_chunks()[:limit]

        result = self.client.search(
            collection_name=self.collection,
            data=[query_embedding],
            limit=limit,
            output_fields=self.output_fields,
        )
        hits = result[0] if result and isinstance(result[0], list) else result
        return [self._record_to_chunk(hit) for hit in hits]

    def list_chunks(self) -> list[Chunk]:
        return [self._record_to_chunk(item) for item in self._query_all(filter_value='id != ""')]

    def list_chunks_for_document(self, document_id: str) -> list[Chunk]:
        return [self._record_to_chunk(item) for item in self._query_all(filter_value=self._document_filter(document_id))]

    def count_chunks_for_document(self, document_id: str) -> int:
        return len(self.list_chunks_for_document(document_id))

    def count_embedded_chunks_for_document(self, document_id: str) -> int:
        return sum(1 for chunk in self.list_chunks_for_document(document_id) if chunk.embedding)

    def get_chunk_stats(self) -> dict[str, dict[str, int]]:
        stats: dict[str, dict[str, int]] = {}
        for chunk in self.list_chunks():
            item = stats.setdefault(chunk.document_id, {"chunk_count": 0, "embedded_chunk_count": 0})
            item["chunk_count"] += 1
            if chunk.embedding:
                item["embedded_chunk_count"] += 1
        return stats

    def _query_all(self, *, filter_value: str) -> list[object]:
        records: list[object] = []
        page_size = max(int(self.query_limit), 1)
        iterator = self.client.query_iterator(
            collection_name=self.collection,
            filter=filter_value,
            output_fields=self.output_fields,
            batch_size=page_size,
        )
        try:
            while True:
                page = iterator.next()
                if not page:
                    break
                records.extend(page)
        finally:
            iterator.close()
        return records

    def _chunk_to_record(self, chunk: Chunk) -> dict[str, object]:
        if not chunk.embedding:
            raise ValueError(
                "MilvusVectorStore requires chunk embeddings. Enable embeddings or use "
                "`AEGIS_VECTOR_STORE_PROVIDER=local`."
            )
        if len(chunk.embedding) != self.dimension:
            raise ValueError(
                f"Chunk embedding dimension {len(chunk.embedding)} does not match "
                f"configured Milvus dimension {self.dimension}."
            )
        return {
            "id": chunk.id,
            "document_id": chunk.document_id,
            "document_title": chunk.document_title,
            "text": chunk.text,
            "chunk_index": chunk.chunk_index,
            "tokens_json": json.dumps(chunk.tokens, ensure_ascii=False),
            "embedding": chunk.embedding,
            "embedding_version": chunk.embedding_version,
            "metadata_json": json.dumps(chunk.metadata, ensure_ascii=False),
        }

    def _record_to_chunk(self, raw: Any) -> Chunk:
        record = self._flatten_record(raw)
        return Chunk(
            id=str(record.get("id", "")),
            document_id=str(record.get("document_id", "")),
            document_title=str(record.get("document_title", "")),
            text=str(record.get("text", "")),
            chunk_index=int(record.get("chunk_index", 0)),
            tokens=self._json_list(record.get("tokens_json")),
            embedding=list(record.get("embedding") or []),
            embedding_version=str(record.get("embedding_version", "")),
            metadata=self._json_dict(record.get("metadata_json")),
        )

    @staticmethod
    def _flatten_record(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict) and hasattr(raw, "to_dict"):
            raw = raw.to_dict()
        if isinstance(raw, dict):
            record = dict(raw)
        else:
            record = {}
            for name in ("id", "entity"):
                if hasattr(raw, name):
                    record[name] = getattr(raw, name)
        entity = record.get("entity")
        if isinstance(entity, dict):
            flattened = dict(entity)
            if "id" not in flattened and "id" in record:
                flattened["id"] = record["id"]
            record = flattened
        meta = record.get("$meta")
        if isinstance(meta, dict):
            for key, value in meta.items():
                record.setdefault(key, value)
        return record

    @staticmethod
    def _json_list(value: object) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value]
        if not isinstance(value, str) or not value:
            return []
        loaded = json.loads(value)
        return [str(item) for item in loaded] if isinstance(loaded, list) else []

    @staticmethod
    def _json_dict(value: object) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if not isinstance(value, str) or not value:
            return {}
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {}

    @staticmethod
    def _document_filter(document_id: str) -> str:
        return f"document_id == {json.dumps(document_id)}"

    @staticmethod
    def _mutation_count(result: object) -> int:
        if isinstance(result, dict):
            for key in ("delete_count", "insert_count", "upsert_count"):
                value = result.get(key)
                if isinstance(value, int):
                    return value
        if isinstance(result, list):
            return len(result)
        return 0
