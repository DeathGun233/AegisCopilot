from __future__ import annotations

from collections import defaultdict

from ..models import Chunk


def assign_chunk_hierarchy(chunks: list[Chunk]) -> list[Chunk]:
    by_path: dict[str, Chunk] = {}
    children_by_parent: dict[str, list[str]] = defaultdict(list)

    for chunk in chunks:
        metadata = dict(chunk.metadata)
        metadata.setdefault("parent_chunk_id", "")
        metadata.setdefault("child_chunk_ids", [])
        chunk.metadata = metadata

    for chunk in sorted(chunks, key=lambda item: item.chunk_index):
        section_path = str(chunk.metadata.get("section_path", "")).strip()
        parent = _nearest_parent(section_path, by_path)
        if parent is not None:
            chunk.metadata["parent_chunk_id"] = parent.id
            children_by_parent[parent.id].append(chunk.id)
        if section_path:
            by_path.setdefault(section_path, chunk)

    for chunk in chunks:
        child_ids = children_by_parent.get(chunk.id, [])
        chunk.metadata["child_chunk_ids"] = child_ids
        if child_ids:
            chunk.metadata["chunk_role"] = "parent"
        elif chunk.metadata.get("parent_chunk_id"):
            chunk.metadata["chunk_role"] = "child"
        else:
            chunk.metadata["chunk_role"] = "standalone"
    return chunks


def _nearest_parent(section_path: str, by_path: dict[str, Chunk]) -> Chunk | None:
    if not section_path or ">" not in section_path:
        return None
    parts = [part.strip() for part in section_path.split(">") if part.strip()]
    for size in range(len(parts) - 1, 0, -1):
        candidate = " > ".join(parts[:size])
        parent = by_path.get(candidate)
        if parent is not None:
            return parent
    return None
