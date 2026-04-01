from pathlib import Path
import sys
import time

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.main import app

client = TestClient(app)


def _login_as_admin() -> dict[str, str]:
    response = client.post(
        "/auth/login",
        json={"username": "admin", "password": settings.admin_password},
    )
    assert response.status_code == 200
    token = response.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_document_and_chat_flow() -> None:
    headers = _login_as_admin()

    create_response = client.post(
        "/documents",
        json={
            "title": "员工请假制度",
            "content": "员工请假需要提前申请，年假需要主管审批。",
            "source_type": "text",
            "department": "hr",
            "version": "v1",
            "tags": ["请假"],
        },
        headers=headers,
    )
    assert create_response.status_code == 200
    document_id = create_response.json()["document"]["id"]

    index_response = client.post("/documents/index", json={"document_id": document_id}, headers=headers)
    assert index_response.status_code == 200
    assert index_response.json()["chunks_created"] >= 1

    chat_response = client.post("/chat", json={"query": "请假流程是什么？"}, headers=headers)
    assert chat_response.status_code == 200
    payload = chat_response.json()
    assert payload["task"]["intent"] == "knowledge_qa"
    assert "请假" in payload["reply"]["content"]


def test_async_reindex_task_flow() -> None:
    headers = _login_as_admin()

    create_response = client.post(
        "/documents",
        json={
            "title": "差旅报销制度",
            "content": "员工报销需要提交发票、行程单和审批单。",
            "source_type": "text",
            "department": "finance",
            "version": "v1",
            "tags": ["报销"],
        },
        headers=headers,
    )
    assert create_response.status_code == 200
    document_id = create_response.json()["document"]["id"]

    reindex_response = client.post(f"/documents/{document_id}/reindex", headers=headers)
    assert reindex_response.status_code == 200
    task = reindex_response.json()["task"]
    assert task["status"] in {"pending", "running"}

    deadline = time.time() + 10
    final_task = task
    while time.time() < deadline:
        task_response = client.get(f"/documents/upload/tasks/{task['id']}", headers=headers)
        assert task_response.status_code == 200
        final_task = task_response.json()["task"]
        if final_task["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.2)

    assert final_task["status"] == "succeeded", final_task
    status_response = client.get(f"/documents/{document_id}/status", headers=headers)
    assert status_response.status_code == 200
    document = status_response.json()["document"]
    assert document["index_state"] == "indexed"
    assert document["chunk_count"] >= 1
