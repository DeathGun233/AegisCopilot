from __future__ import annotations

import json
from collections.abc import Iterable
from urllib import request

from ..config import settings
from .text import normalize_text


class EmbeddingService:
    def get_version(self) -> str:
        if not self.is_enabled():
            return "disabled"
        return f"{settings.embedding_provider}:{settings.embedding_model}:{settings.embedding_dimensions}"

    def is_enabled(self) -> bool:
        return (
            settings.embedding_provider == "openai-compatible"
            and bool(settings.embedding_base_url)
            and bool(settings.embedding_api_key)
        )

    def get_runtime(self) -> dict[str, object]:
        return {
            "provider": settings.embedding_provider,
            "model": settings.embedding_model,
            "base_url": settings.embedding_base_url,
            "dimensions": settings.embedding_dimensions,
            "version": self.get_version(),
            "api_key_configured": bool(settings.embedding_api_key),
            "enabled": self.is_enabled(),
        }

    def embed_text(self, text: str) -> list[float]:
        vectors = self.embed_texts([text])
        return vectors[0] if vectors else []

    def embed_texts(self, texts: Iterable[str]) -> list[list[float]]:
        normalized_texts = [normalize_text(text) for text in texts]
        if not normalized_texts:
            return []
        if not self.is_enabled():
            return []

        vectors: list[list[float]] = []
        batch_size = max(1, settings.embedding_batch_size)
        for start in range(0, len(normalized_texts), batch_size):
            vectors.extend(self._call_openai_compatible(normalized_texts[start : start + batch_size]))
        return vectors

    def _call_openai_compatible(self, inputs: list[str]) -> list[list[float]]:
        payload = {
            "model": settings.embedding_model,
            "input": inputs,
            "encoding_format": "float",
        }
        if settings.embedding_dimensions > 0:
            payload["dimensions"] = settings.embedding_dimensions

        req = request.Request(
            url=f"{settings.embedding_base_url.rstrip('/')}/embeddings",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.embedding_api_key}",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=60) as response:
                body = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # pragma: no cover - network failures are environment-specific
            raise RuntimeError(f"调用 embedding 接口失败：{exc}") from exc

        rows = sorted(body.get("data", []), key=lambda item: item.get("index", 0))
        vectors = [item.get("embedding", []) for item in rows]
        if len(vectors) != len(inputs):
            raise RuntimeError("embedding 返回数量与输入数量不一致")
        if not all(isinstance(vector, list) and vector for vector in vectors):
            raise RuntimeError("embedding 接口返回了空向量")
        return [[float(value) for value in vector] for vector in vectors]
