import os
from pathlib import Path

from pydantic import BaseModel, Field


def _read_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _pick_api_key() -> str:
    return (
        os.getenv("AEGIS_LLM_API_KEY")
        or os.getenv("OPEN_AI_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    )


def _pick_embedding_api_key() -> str:
    return os.getenv("AEGIS_EMBEDDING_API_KEY") or _pick_api_key()


def _pick_rerank_api_key() -> str:
    return os.getenv("AEGIS_RERANK_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or _pick_api_key()


class Settings(BaseModel):
    app_name: str = "AegisCopilot API"
    app_version: str = "0.1.0"
    database_url: str = os.getenv("AEGIS_DATABASE_URL", "")
    storage_dir: Path = Field(default=Path(__file__).resolve().parents[2] / "backend" / "storage")
    reports_dir: Path = Field(default=Path(__file__).resolve().parents[2] / "backend" / "storage" / "reports")
    max_history_messages: int = 8
    default_retrieval_top_k: int = int(os.getenv("AEGIS_TOP_K", "5"))
    default_retrieval_candidate_k: int = int(os.getenv("AEGIS_RETRIEVAL_CANDIDATE_K", "12"))
    default_keyword_weight: float = float(os.getenv("AEGIS_KEYWORD_WEIGHT", "0.55"))
    default_semantic_weight: float = float(os.getenv("AEGIS_SEMANTIC_WEIGHT", "0.45"))
    default_rerank_weight: float = float(os.getenv("AEGIS_RERANK_WEIGHT", "0.6"))
    default_retrieval_min_score: float = float(os.getenv("AEGIS_RETRIEVAL_MIN_SCORE", "0.08"))
    min_grounding_score: float = float(os.getenv("AEGIS_MIN_GROUNDING_SCORE", "0.18"))
    rerank_provider: str = os.getenv("AEGIS_RERANK_PROVIDER", "heuristic").strip().lower() or "heuristic"
    rerank_model: str = os.getenv("AEGIS_RERANK_MODEL", "qwen3-vl-rerank")
    rerank_base_url: str = os.getenv(
        "AEGIS_RERANK_BASE_URL",
        "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
    )
    rerank_api_key: str = _pick_rerank_api_key()
    rerank_top_n: int = int(os.getenv("AEGIS_RERANK_TOP_N", "40"))
    rerank_timeout_seconds: float = float(os.getenv("AEGIS_RERANK_TIMEOUT_SECONDS", "15"))
    llm_provider: str = os.getenv(
        "AEGIS_LLM_PROVIDER",
        "openai-compatible" if _pick_api_key() else "mock",
    )
    llm_model: str = os.getenv("AEGIS_LLM_MODEL", "qwen3-max")
    llm_base_url: str = os.getenv(
        "AEGIS_LLM_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    llm_api_key: str = _pick_api_key()
    embedding_provider: str = os.getenv(
        "AEGIS_EMBEDDING_PROVIDER",
        "openai-compatible" if _pick_embedding_api_key() else "disabled",
    )
    embedding_model: str = os.getenv("AEGIS_EMBEDDING_MODEL", "text-embedding-v4")
    embedding_base_url: str = os.getenv("AEGIS_EMBEDDING_BASE_URL", llm_base_url)
    embedding_api_key: str = _pick_embedding_api_key()
    embedding_dimensions: int = int(os.getenv("AEGIS_EMBEDDING_DIMENSIONS", "1024"))
    embedding_batch_size: int = int(os.getenv("AEGIS_EMBEDDING_BATCH_SIZE", "10"))
    vector_store_provider: str = os.getenv("AEGIS_VECTOR_STORE_PROVIDER", "local").strip().lower() or "local"
    milvus_uri: str = os.getenv("AEGIS_MILVUS_URI", "http://localhost:19530")
    milvus_token: str = os.getenv("AEGIS_MILVUS_TOKEN", "")
    milvus_collection: str = os.getenv("AEGIS_MILVUS_COLLECTION", "aegis_chunks")
    environment: str = os.getenv("AEGIS_ENV", "local")
    auth_session_ttl_minutes: int = int(os.getenv("AEGIS_AUTH_SESSION_TTL_MINUTES", "480"))
    persist_auth_sessions: bool = _read_bool("AEGIS_PERSIST_AUTH_SESSIONS", False)
    allow_demo_auth: bool = _read_bool(
        "AEGIS_ALLOW_DEMO_AUTH",
        os.getenv("AEGIS_ENV", "local").strip().lower() == "local",
    )
    admin_password: str = os.getenv("AEGIS_ADMIN_PASSWORD", "admin123")
    member_password: str = os.getenv("AEGIS_MEMBER_PASSWORD", "member123")


def ensure_storage_dirs() -> None:
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    settings.reports_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
ensure_storage_dirs()
