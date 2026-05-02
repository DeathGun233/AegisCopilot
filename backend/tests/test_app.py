from importlib import import_module
import json
from pathlib import Path
import sys
import time

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import ensure_storage_dirs, settings
from app.deps import reset_container


@pytest.fixture()
def client(tmp_path: Path):
    original_settings = {
        "storage_dir": settings.storage_dir,
        "reports_dir": settings.reports_dir,
        "llm_provider": settings.llm_provider,
        "llm_base_url": settings.llm_base_url,
        "llm_api_key": settings.llm_api_key,
        "embedding_provider": settings.embedding_provider,
        "embedding_base_url": settings.embedding_base_url,
        "embedding_api_key": settings.embedding_api_key,
        "database_url": settings.database_url,
        "vector_store_provider": settings.vector_store_provider,
        "milvus_uri": settings.milvus_uri,
        "milvus_collection": settings.milvus_collection,
    }

    settings.storage_dir = tmp_path / "storage"
    settings.reports_dir = settings.storage_dir / "reports"
    settings.llm_provider = "mock"
    settings.llm_base_url = ""
    settings.llm_api_key = ""
    settings.embedding_provider = "disabled"
    settings.embedding_base_url = ""
    settings.embedding_api_key = ""
    settings.database_url = ""
    settings.vector_store_provider = "local"
    settings.milvus_uri = "http://localhost:19530"
    settings.milvus_collection = "aegis_chunks"
    ensure_storage_dirs()
    reset_container()

    app_module = import_module("app.main")
    with TestClient(app_module.app) as test_client:
        yield test_client

    for key, value in original_settings.items():
        setattr(settings, key, value)
    ensure_storage_dirs()
    reset_container()


def _login_as_admin(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/auth/login",
        json={"username": "admin", "password": settings.admin_password},
    )
    assert response.status_code == 200
    token = response.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _login_as_member(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/auth/login",
        json={"username": "member", "password": settings.member_password},
    )
    assert response.status_code == 200
    token = response.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _wait_for_task_completion(
    client: TestClient,
    task_id: str,
    headers: dict[str, str],
    timeout: float = 5.0,
) -> dict:
    deadline = time.time() + timeout
    final_task: dict | None = None
    while time.time() < deadline:
        task_response = client.get(f"/documents/upload/tasks/{task_id}", headers=headers)
        assert task_response.status_code == 200
        final_task = task_response.json()["task"]
        if final_task["status"] in {"succeeded", "failed"}:
            return final_task
        time.sleep(0.05)
    assert final_task is not None
    return final_task


def _parse_sse_frames(body: str) -> list[dict]:
    frames: list[dict] = []
    for block in body.split("\n\n"):
        if not block.startswith("data: "):
            continue
        frames.append(json.loads(block[6:]))
    return frames


def _with_failing_model_settings():
    original = {
        "llm_provider": settings.llm_provider,
        "llm_base_url": settings.llm_base_url,
        "llm_api_key": settings.llm_api_key,
    }
    settings.llm_provider = "openai-compatible"
    settings.llm_base_url = "http://127.0.0.1:9"
    settings.llm_api_key = "test-key"
    reset_container()
    return original


def _restore_model_settings(original: dict[str, str]) -> None:
    for key, value in original.items():
        setattr(settings, key, value)
    reset_container()


def _with_auth_settings(**updates: object) -> dict[str, object]:
    original = {key: getattr(settings, key) for key in updates}
    for key, value in updates.items():
        setattr(settings, key, value)
    reset_container()
    return original


def _restore_auth_settings(original: dict[str, object]) -> None:
    for key, value in original.items():
        setattr(settings, key, value)
    reset_container()


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_system_status_reports_readiness_and_providers(client: TestClient) -> None:
    headers = _login_as_admin(client)

    response = client.get("/system/status", headers=headers)

    assert response.status_code == 200
    payload = response.json()["status"]
    assert payload["status"] == "ready"
    assert payload["ready"] is True
    assert payload["providers"]["database"]["provider"] == "json"
    assert payload["providers"]["database"]["status"] == "ok"
    assert payload["providers"]["vector"]["provider"] == "local"
    assert payload["providers"]["vector"]["status"] == "ok"
    assert payload["providers"]["vector"]["detail"]["selection_mode"] == "startup"
    assert payload["providers"]["vector"]["detail"]["restart_required_for_changes"] is True
    assert payload["providers"]["vector"]["detail"]["available_providers"] == ["local", "milvus"]
    assert payload["providers"]["embedding"]["provider"] == "disabled"
    assert payload["providers"]["llm"]["provider"] == "mock"
    assert payload["document_tasks"]["queued"] == 0
    assert payload["document_tasks"]["running"] == 0
    assert payload["document_tasks"]["failed"] == 0
    assert payload["document_tasks"]["active"] == 0


def test_system_status_requires_admin(client: TestClient) -> None:
    headers = _login_as_member(client)

    response = client.get("/system/status", headers=headers)

    assert response.status_code == 403


def test_retrieval_debug_requires_admin(client: TestClient) -> None:
    headers = _login_as_member(client)

    response = client.post("/retrieval/debug", json={"query": "leave approval"}, headers=headers)

    assert response.status_code == 403


def test_retrieval_debug_uses_trial_settings_without_persisting(client: TestClient) -> None:
    headers = _login_as_admin(client)

    create_response = client.post(
        "/documents",
        json={
            "title": "Leave Approval Policy",
            "content": (
                "Employees submit leave requests one business day in advance. "
                "Managers approve annual leave before the leave starts."
            ),
            "source_type": "text",
            "department": "hr",
            "version": "v1",
            "tags": ["leave"],
        },
        headers=headers,
    )
    assert create_response.status_code == 200
    document_id = create_response.json()["document"]["id"]
    assert client.post("/documents/index", json={"document_id": document_id}, headers=headers).status_code == 200

    original_settings = client.get("/retrieval/settings", headers=headers).json()["settings"]
    response = client.post(
        "/retrieval/debug",
        json={
            "query": "leave approval",
            "top_k": 1,
            "candidate_k": 3,
            "keyword_weight": 1.0,
            "semantic_weight": 0.0,
            "rerank_weight": 0.2,
            "min_score": 0.01,
        },
        headers=headers,
    )

    assert response.status_code == 200
    debug = response.json()["debug"]
    assert debug["settings"]["top_k"] == 1
    assert debug["settings"]["candidate_k"] == 3
    assert debug["query_variants"]
    assert debug["results"]
    assert debug["candidates"][0]["filter_reason"] in {
        "selected",
        "outside_top_k",
        "duplicate",
        "below_min_score",
    }
    assert "keyword_score" in debug["candidates"][0]
    assert "semantic_score" in debug["candidates"][0]
    assert "rerank_score" in debug["candidates"][0]

    persisted_settings = client.get("/retrieval/settings", headers=headers).json()["settings"]
    assert persisted_settings == original_settings


def test_index_document_surfaces_vector_store_configuration_errors(client: TestClient) -> None:
    from app.deps import get_container

    headers = _login_as_admin(client)
    container = get_container()
    original_index_document = container.document_service.index_document

    def fail_index(document_id: str) -> int:
        raise ValueError("MilvusVectorStore requires chunk embeddings.")

    container.document_service.index_document = fail_index
    try:
        response = client.post("/documents/index", json={"document_id": "doc-needs-embedding"}, headers=headers)
    finally:
        container.document_service.index_document = original_index_document

    assert response.status_code == 400
    assert "MilvusVectorStore requires chunk embeddings" in response.json()["detail"]


def test_document_and_chat_flow(client: TestClient) -> None:
    headers = _login_as_admin(client)

    create_response = client.post(
        "/documents",
        json={
            "title": "Employee Leave Policy",
            "content": (
                "Employees must submit leave requests one business day in advance. "
                "Annual leave requires manager approval."
            ),
            "source_type": "text",
            "department": "hr",
            "version": "v1",
            "tags": ["leave"],
        },
        headers=headers,
    )
    assert create_response.status_code == 200
    document_id = create_response.json()["document"]["id"]

    index_response = client.post("/documents/index", json={"document_id": document_id}, headers=headers)
    assert index_response.status_code == 200
    assert index_response.json()["chunks_created"] >= 1

    chat_response = client.post(
        "/chat",
        json={"query": "What is the employee leave process?"},
        headers=headers,
    )
    assert chat_response.status_code == 200
    payload = chat_response.json()
    assert payload["task"]["intent"] == "knowledge_qa"
    assert "Employees" in payload["reply"]["content"]


def test_stream_chat_reports_progress_before_answer(client: TestClient) -> None:
    headers = _login_as_admin(client)

    create_response = client.post(
        "/documents",
        json={
            "title": "Release Checklist",
            "content": (
                "Before production release, teams must complete code review, "
                "run regression checks, and confirm rollback procedures."
            ),
            "source_type": "text",
            "department": "engineering",
            "version": "v1",
            "tags": ["release"],
        },
        headers=headers,
    )
    assert create_response.status_code == 200
    document_id = create_response.json()["document"]["id"]

    index_response = client.post("/documents/index", json={"document_id": document_id}, headers=headers)
    assert index_response.status_code == 200

    with client.stream(
        "POST",
        "/chat/stream",
        json={"query": "What should we check before production release?"},
        headers=headers,
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache, no-transform"
        body = "".join(response.iter_text())

    events = _parse_sse_frames(body)
    assert events[0]["type"] == "conversation"

    status_events = [event for event in events if event["type"] == "status"]
    status_stages = [event["stage"] for event in status_events]
    assert "understand_query" in status_stages
    assert "retrieve_context" in status_stages
    assert "generate_answer" in status_stages

    retrieve_index = next(index for index, event in enumerate(events) if event.get("stage") == "retrieve_context")
    generate_index = next(index for index, event in enumerate(events) if event.get("stage") == "generate_answer")
    first_delta_index = next(index for index, event in enumerate(events) if event["type"] == "delta")

    assert retrieve_index < generate_index < first_delta_index
    assert any(event["message"].startswith("已完成检索") for event in status_events)


def test_chat_surfaces_model_fallback(client: TestClient) -> None:
    original = _with_failing_model_settings()
    try:
        headers = _login_as_admin(client)

        create_response = client.post(
            "/documents",
            json={
                "title": "Incident Response Guide",
                "content": "Teams should confirm ownership, assess impact, and communicate mitigation progress.",
                "source_type": "text",
                "department": "ops",
                "version": "v1",
                "tags": ["incident"],
            },
            headers=headers,
        )
        assert create_response.status_code == 200
        document_id = create_response.json()["document"]["id"]

        index_response = client.post("/documents/index", json={"document_id": document_id}, headers=headers)
        assert index_response.status_code == 200

        chat_response = client.post(
            "/chat",
            json={"query": "What should incident response teams do first?"},
            headers=headers,
        )
        assert chat_response.status_code == 200
        payload = chat_response.json()

        assert payload["task"]["provider"] == "mock-fallback"
        assert "模型服务不可用" in payload["reply"]["content"]
        assert any(item.get("generation_degraded") is True for item in payload["task"]["trace"])
    finally:
        _restore_model_settings(original)


def test_stream_chat_surfaces_model_fallback(client: TestClient) -> None:
    original = _with_failing_model_settings()
    try:
        headers = _login_as_admin(client)

        create_response = client.post(
            "/documents",
            json={
                "title": "Vendor Onboarding Guide",
                "content": "Teams must verify contracts, collect tax documents, and confirm payment details.",
                "source_type": "text",
                "department": "finance",
                "version": "v1",
                "tags": ["vendor"],
            },
            headers=headers,
        )
        assert create_response.status_code == 200
        document_id = create_response.json()["document"]["id"]

        index_response = client.post("/documents/index", json={"document_id": document_id}, headers=headers)
        assert index_response.status_code == 200

        with client.stream(
            "POST",
            "/chat/stream",
            json={"query": "What should we verify during vendor onboarding?"},
            headers=headers,
        ) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())

        events = _parse_sse_frames(body)
        reply = "".join(event["content"] for event in events if event["type"] == "delta")
        done_event = next(event for event in events if event["type"] == "done")

        assert any(event.get("stage") == "generation_fallback" for event in events if event["type"] == "status")
        assert "模型服务不可用" in reply
        assert done_event["task"]["provider"] == "mock-fallback"
    finally:
        _restore_model_settings(original)


def test_session_expiry_invalidates_token(client: TestClient) -> None:
    headers = _login_as_admin(client)
    token = headers["Authorization"].split(" ", 1)[1]

    from app.deps import get_container

    session = get_container().sessions.get(token)
    assert session is not None
    session.expires_at = session.created_at
    get_container().sessions.save(session)

    response = client.get("/auth/me", headers=headers)
    assert response.status_code == 401


def test_sessions_do_not_persist_by_default(client: TestClient) -> None:
    headers = _login_as_admin(client)
    assert headers["Authorization"].startswith("Bearer ")
    assert not (settings.storage_dir / "sessions.json").exists()


def test_seed_skips_indexing_when_milvus_embeddings_are_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import seed

    class FakeDocumentService:
        def __init__(self) -> None:
            self.created = []
            self.indexed = []

        def list_documents(self) -> list:
            return []

        def create_document(self, **kwargs):
            document = type("Document", (), {"id": f"doc-{len(self.created) + 1}"})()
            self.created.append(kwargs)
            return document

        def index_document(self, document_id: str) -> int:
            self.indexed.append(document_id)
            raise ValueError("MilvusVectorStore requires chunk embeddings.")

    class FakeEmbeddingService:
        def is_enabled(self) -> bool:
            return False

    fake_document_service = FakeDocumentService()
    fake_container = type(
        "Container",
        (),
        {
            "document_service": fake_document_service,
            "embedding_service": FakeEmbeddingService(),
        },
    )()

    original_provider = settings.vector_store_provider
    settings.vector_store_provider = "milvus"
    monkeypatch.setattr(seed, "get_container", lambda: fake_container)
    try:
        seed.main()
    finally:
        settings.vector_store_provider = original_provider

    assert len(fake_document_service.created) == len(seed.SAMPLE_DOCS)
    assert fake_document_service.indexed == []


def test_non_demo_environment_rejects_default_passwords(client: TestClient) -> None:
    original = _with_auth_settings(
        allow_demo_auth=False,
        admin_password="admin123",
        member_password="member123",
    )
    try:
        response = client.post(
            "/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert response.status_code == 401
        assert "默认演示密码" in response.json()["detail"]
    finally:
        _restore_auth_settings(original)


def test_async_reindex_task_flow(client: TestClient) -> None:
    headers = _login_as_admin(client)

    create_response = client.post(
        "/documents",
        json={
            "title": "Expense Reimbursement Policy",
            "content": "Employees must submit invoices, itineraries, and approvals for reimbursement.",
            "source_type": "text",
            "department": "finance",
            "version": "v1",
            "tags": ["expense"],
        },
        headers=headers,
    )
    assert create_response.status_code == 200
    document_id = create_response.json()["document"]["id"]

    reindex_response = client.post(f"/documents/{document_id}/reindex", headers=headers)
    assert reindex_response.status_code == 200
    task = reindex_response.json()["task"]
    assert task["status"] in {"pending", "running"}

    final_task = _wait_for_task_completion(client, task["id"], headers)
    assert final_task["status"] == "succeeded", final_task

    status_response = client.get(f"/documents/{document_id}/status", headers=headers)
    assert status_response.status_code == 200
    document = status_response.json()["document"]
    assert document["index_state"] == "indexed"
    assert document["chunk_count"] >= 1


def test_member_cannot_access_admin_routes(client: TestClient) -> None:
    headers = _login_as_member(client)

    users_response = client.get("/users", headers=headers)
    assert users_response.status_code == 403

    create_response = client.post(
        "/documents",
        json={
            "title": "Member Should Not Create Documents",
            "content": "This request should be rejected by admin permission checks.",
            "source_type": "text",
            "department": "general",
            "version": "v1",
            "tags": ["permission"],
        },
        headers=headers,
    )
    assert create_response.status_code == 403


def test_conversation_is_user_scoped(client: TestClient) -> None:
    admin_headers = _login_as_admin(client)
    member_headers = _login_as_member(client)

    create_response = client.post(
        "/conversations",
        json={"title": "Admin Private Conversation"},
        headers=admin_headers,
    )
    assert create_response.status_code == 200
    conversation_id = create_response.json()["conversation"]["id"]

    member_list_response = client.get("/conversations", headers=member_headers)
    assert member_list_response.status_code == 200
    conversation_ids = [item["id"] for item in member_list_response.json()["conversations"]]
    assert conversation_id not in conversation_ids

    member_detail_response = client.get(f"/conversations/{conversation_id}", headers=member_headers)
    assert member_detail_response.status_code == 404


def test_sql_persistence_survives_container_reset(tmp_path: Path) -> None:
    original_settings = {
        "storage_dir": settings.storage_dir,
        "reports_dir": settings.reports_dir,
        "llm_provider": settings.llm_provider,
        "llm_base_url": settings.llm_base_url,
        "llm_api_key": settings.llm_api_key,
        "embedding_provider": settings.embedding_provider,
        "embedding_base_url": settings.embedding_base_url,
        "embedding_api_key": settings.embedding_api_key,
        "database_url": getattr(settings, "database_url", ""),
    }

    settings.storage_dir = tmp_path / "storage"
    settings.reports_dir = settings.storage_dir / "reports"
    settings.llm_provider = "mock"
    settings.llm_base_url = ""
    settings.llm_api_key = ""
    settings.embedding_provider = "disabled"
    settings.embedding_base_url = ""
    settings.embedding_api_key = ""
    settings.database_url = f"sqlite:///{(tmp_path / 'app.db').as_posix()}"
    ensure_storage_dirs()
    reset_container()

    app_module = import_module("app.main")
    with TestClient(app_module.app) as first_client:
        headers = _login_as_admin(first_client)
        create_response = first_client.post(
            "/documents",
            json={
                "title": "SQL Persistence Policy",
                "content": "This record should survive container reset when SQL storage is enabled.",
                "source_type": "text",
                "department": "ops",
                "version": "v1",
                "tags": ["sql"],
            },
            headers=headers,
        )
        assert create_response.status_code == 200
        created_id = create_response.json()["document"]["id"]

        convo_response = first_client.post(
            "/conversations",
            json={"title": "SQL Backed Conversation"},
            headers=headers,
        )
        assert convo_response.status_code == 200
        created_conversation_id = convo_response.json()["conversation"]["id"]

    reset_container()

    with TestClient(app_module.app) as second_client:
        headers = _login_as_admin(second_client)

        list_response = second_client.get("/documents", headers=headers)
        assert list_response.status_code == 200
        document_ids = [item["id"] for item in list_response.json()["documents"]]
        assert created_id in document_ids

        conversations_response = second_client.get("/conversations", headers=headers)
        assert conversations_response.status_code == 200
        conversation_ids = [item["id"] for item in conversations_response.json()["conversations"]]
        assert created_conversation_id in conversation_ids

    for key, value in original_settings.items():
        setattr(settings, key, value)
    ensure_storage_dirs()
    reset_container()


def test_sql_runtime_settings_survive_container_reset(tmp_path: Path) -> None:
    original_settings = {
        "storage_dir": settings.storage_dir,
        "reports_dir": settings.reports_dir,
        "llm_provider": settings.llm_provider,
        "llm_base_url": settings.llm_base_url,
        "llm_api_key": settings.llm_api_key,
        "embedding_provider": settings.embedding_provider,
        "embedding_base_url": settings.embedding_base_url,
        "embedding_api_key": settings.embedding_api_key,
        "database_url": settings.database_url,
    }

    settings.storage_dir = tmp_path / "storage"
    settings.reports_dir = settings.storage_dir / "reports"
    settings.llm_provider = "mock"
    settings.llm_base_url = ""
    settings.llm_api_key = ""
    settings.embedding_provider = "disabled"
    settings.embedding_base_url = ""
    settings.embedding_api_key = ""
    settings.database_url = f"sqlite:///{(tmp_path / 'runtime.db').as_posix()}"
    ensure_storage_dirs()
    reset_container()

    app_module = import_module("app.main")
    with TestClient(app_module.app) as first_client:
        headers = _login_as_admin(first_client)

        select_response = first_client.post(
            "/models/select",
            json={"model_id": "qwen-plus"},
            headers=headers,
        )
        assert select_response.status_code == 200

        retrieval_response = first_client.post(
            "/retrieval/settings",
            json={
                "top_k": 7,
                "candidate_k": 15,
                "keyword_weight": 0.5,
                "semantic_weight": 0.5,
                "rerank_weight": 0.4,
                "min_score": 0.12,
            },
            headers=headers,
        )
        assert retrieval_response.status_code == 200

    runtime_model_path = settings.storage_dir / "runtime_model.json"
    runtime_retrieval_path = settings.storage_dir / "runtime_retrieval.json"
    if runtime_model_path.exists():
        runtime_model_path.unlink()
    if runtime_retrieval_path.exists():
        runtime_retrieval_path.unlink()

    reset_container()

    with TestClient(app_module.app) as second_client:
        headers = _login_as_admin(second_client)

        catalog_response = second_client.get("/models", headers=headers)
        assert catalog_response.status_code == 200
        assert catalog_response.json()["catalog"]["active_model"] == "qwen-plus"

        settings_response = second_client.get("/retrieval/settings", headers=headers)
        assert settings_response.status_code == 200
        payload = settings_response.json()["settings"]
        assert payload["top_k"] == 7
        assert payload["candidate_k"] == 15
        assert payload["min_score"] == pytest.approx(0.12)

    for key, value in original_settings.items():
        setattr(settings, key, value)
    ensure_storage_dirs()
    reset_container()
