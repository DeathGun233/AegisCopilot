from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "migrate_json_to_sql.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("migrate_json_to_sql", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_migration_backfills_chunk_hierarchy_metadata(tmp_path: Path) -> None:
    module = _load_module()
    from app.models import Chunk, Document, DocumentIndexState, utc_now
    from app.sql_repositories import SqlDatabase, SqlDocumentRepository

    now = utc_now()
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)
    document = Document(
        id="doc-hierarchy",
        title="欧洲 DDP 渠道清关资料表",
        content="content",
        source_type="text",
        department="logistics",
        version="v1",
        created_at=now,
        updated_at=now,
        indexed_at=now,
        index_state=DocumentIndexState.indexed,
    )
    parent = Chunk(
        id="chunk-parent",
        document_id=document.id,
        document_title=document.title,
        text="德国",
        chunk_index=0,
        tokens=["德国"],
        metadata={"section_path": "欧洲 DDP 渠道清关资料表 > 德国", "section_level": 2},
    )
    child = Chunk(
        id="chunk-child",
        document_id=document.id,
        document_title=document.title,
        text="带电产品需要 MSDS。",
        chunk_index=1,
        tokens=["带电", "msds"],
        metadata={"section_path": "欧洲 DDP 渠道清关资料表 > 德国 > 带电产品", "section_level": 3},
    )
    (storage_dir / "documents.json").write_text(
        json.dumps([document.model_dump(mode="json")], ensure_ascii=False),
        encoding="utf-8",
    )
    (storage_dir / "chunks.json").write_text(
        json.dumps([parent.model_dump(mode="json"), child.model_dump(mode="json")], ensure_ascii=False),
        encoding="utf-8",
    )
    database_url = f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"

    assert module.main(["--storage-dir", str(storage_dir), "--database-url", database_url]) == 0

    chunks = SqlDocumentRepository(SqlDatabase(database_url)).list_chunks_for_document(document.id)
    migrated_child = next(chunk for chunk in chunks if chunk.id == "chunk-child")
    migrated_parent = next(chunk for chunk in chunks if chunk.id == "chunk-parent")
    assert migrated_child.metadata["parent_chunk_id"] == "chunk-parent"
    assert "chunk-child" in migrated_parent.metadata["child_chunk_ids"]
