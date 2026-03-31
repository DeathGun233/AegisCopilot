import os
from pathlib import Path

from pydantic import BaseModel, Field


def _pick_api_key() -> str:
    return (
        os.getenv("AEGIS_LLM_API_KEY")
        or os.getenv("OPEN_AI_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    )


class Settings(BaseModel):
    app_name: str = "AegisCopilot API"
    app_version: str = "0.1.0"
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
    environment: str = os.getenv("AEGIS_ENV", "local")
    admin_password: str = os.getenv("AEGIS_ADMIN_PASSWORD", "admin123")
    member_password: str = os.getenv("AEGIS_MEMBER_PASSWORD", "member123")


settings = Settings()
settings.storage_dir.mkdir(parents=True, exist_ok=True)
settings.reports_dir.mkdir(parents=True, exist_ok=True)
