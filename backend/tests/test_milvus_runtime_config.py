from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_backend_image_installs_milvus_extra() -> None:
    dockerfile = (REPO_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")

    assert 'pip install --no-cache-dir -e ".[milvus]"' in dockerfile


def test_compose_defaults_backend_to_milvus() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "AEGIS_VECTOR_STORE_PROVIDER: ${AEGIS_VECTOR_STORE_PROVIDER:-milvus}" in compose
    assert "milvus:" in compose
    assert "milvus-etcd:" in compose
    assert "milvus-minio:" in compose
    assert "profiles:" not in compose
    assert "AEGIS_EMBEDDING_API_KEY:" in compose
    assert "AEGIS_EMBEDDING_PROVIDER:" in compose
    assert "AEGIS_LLM_PROVIDER: ${AEGIS_LLM_PROVIDER:-openai-compatible}" in compose
    assert "VITE_API_BASE_URL: ${VITE_API_BASE_URL:-http://127.0.0.1:8000}" in compose


def test_env_example_advertises_milvus_provider() -> None:
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")

    assert "AEGIS_VECTOR_STORE_PROVIDER=milvus" in env_example
    assert "AEGIS_MILVUS_URI=http://localhost:19530" in env_example
    assert "AEGIS_MILVUS_COLLECTION=aegis_chunks" in env_example
