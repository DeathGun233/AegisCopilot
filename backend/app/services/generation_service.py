from __future__ import annotations

import json
from collections.abc import Generator
from dataclasses import dataclass
from urllib import request

from ..config import settings
from ..models import RetrievalResult
from .runtime_models import RuntimeModelService


MAX_EVIDENCE_ITEMS = 6


@dataclass(frozen=True)
class GenerationResult:
    content: str
    provider: str
    degraded: bool = False
    fallback_reason: str = ""


@dataclass(frozen=True)
class StreamGenerationEvent:
    type: str
    content: str = ""
    provider: str = ""
    degraded: bool = False
    fallback_reason: str = ""


class GenerationService:
    def __init__(self, runtime_models: RuntimeModelService) -> None:
        self.runtime_models = runtime_models

    @property
    def provider(self) -> str:
        return str(self.runtime_models.get_runtime()["provider"])

    @property
    def model(self) -> str:
        return str(self.runtime_models.get_runtime()["model"])

    def generate(
        self,
        *,
        query: str,
        intent: str,
        retrieval_results: list[RetrievalResult],
        conversation_summary: str,
    ) -> GenerationResult:
        runtime = self.runtime_models.get_runtime()
        if runtime["provider"] == "openai-compatible" and runtime["base_url"] and settings.llm_api_key:
            try:
                return GenerationResult(
                    content=self._call_openai_compatible(
                        query=query,
                        intent=intent,
                        retrieval_results=retrieval_results,
                        conversation_summary=conversation_summary,
                        model=str(runtime["model"]),
                        base_url=str(runtime["base_url"]),
                    ),
                    provider=str(runtime["provider"]),
                )
            except Exception as exc:
                return self._degraded_result(retrieval_results, self._format_fallback_reason(exc))

        if runtime["provider"] == "openai-compatible":
            return self._degraded_result(retrieval_results, self._missing_configuration_reason(runtime))

        return GenerationResult(
            content=self._mock_generate(retrieval_results),
            provider=str(runtime["provider"]),
        )

    def stream_generate(
        self,
        *,
        query: str,
        intent: str,
        retrieval_results: list[RetrievalResult],
        conversation_summary: str,
    ) -> Generator[StreamGenerationEvent, None, None]:
        runtime = self.runtime_models.get_runtime()
        if runtime["provider"] == "openai-compatible" and runtime["base_url"] and settings.llm_api_key:
            try:
                yield StreamGenerationEvent(type="metadata", provider=str(runtime["provider"]))
                yield from self._call_openai_compatible_stream(
                    query=query,
                    intent=intent,
                    retrieval_results=retrieval_results,
                    conversation_summary=conversation_summary,
                    model=str(runtime["model"]),
                    base_url=str(runtime["base_url"]),
                )
                return
            except Exception as exc:
                yield from self._stream_degraded_result(
                    retrieval_results,
                    self._format_fallback_reason(exc),
                )
                return

        if runtime["provider"] == "openai-compatible":
            yield from self._stream_degraded_result(
                retrieval_results,
                self._missing_configuration_reason(runtime),
            )
            return

        yield StreamGenerationEvent(type="metadata", provider=str(runtime["provider"]))
        for chunk in self._chunk_text(self._mock_generate(retrieval_results)):
            yield StreamGenerationEvent(type="delta", content=chunk, provider=str(runtime["provider"]))

    @staticmethod
    def _mock_generate(retrieval_results: list[RetrievalResult]) -> str:
        if retrieval_results:
            lead = retrieval_results[0]
            return f"依据《{lead.document_title}》，可以捡订：{lead.text[:90].strip()}"
        return "当前知识库证据不足，建议补充文档或把问题问得更具体一些。"

    def _call_openai_compatible(
        self,
        *,
        query: str,
        intent: str,
        retrieval_results: list[RetrievalResult],
        conversation_summary: str,
        model: str,
        base_url: str,
    ) -> str:
        payload = self._build_payload(
            query=query,
            intent=intent,
            retrieval_results=retrieval_results,
            conversation_summary=conversation_summary,
            model=model,
            stream=False,
        )
        req = request.Request(
            url=f"{base_url.rstrip('/')}/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.llm_api_key}",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

    def _call_openai_compatible_stream(
        self,
        *,
        query: str,
        intent: str,
        retrieval_results: list[RetrievalResult],
        conversation_summary: str,
        model: str,
        base_url: str,
    ) -> Generator[StreamGenerationEvent, None, None]:
        payload = self._build_payload(
            query=query,
            intent=intent,
            retrieval_results=retrieval_results,
            conversation_summary=conversation_summary,
            model=model,
            stream=True,
        )
        req = request.Request(
            url=f"{base_url.rstrip('/')}/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.llm_api_key}",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=90) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                packet = json.loads(data)
                delta = packet["choices"][0].get("delta", {}).get("content")
                if isinstance(delta, str) and delta:
                    yield StreamGenerationEvent(type="delta", content=delta, provider="openai-compatible")

    @staticmethod
    def _build_payload(
        *,
        query: str,
        intent: str,
        retrieval_results: list[RetrievalResult],
        conversation_summary: str,
        model: str,
        stream: bool,
    ) -> bytes:
        prompt = {
            "task": "请基于证据回答用户问题",
            "intent": intent,
            "query": query,
            "conversation_summary": conversation_summary,
            "evidence": [
                {
                    "source": item.display_source or item.source,
                    "document_title": item.document_title,
                    "text": item.text,
                    "score": item.score,
                    "keyword_score": item.keyword_score,
                    "semantic_score": item.semantic_score,
                }
                for item in retrieval_results[:MAX_EVIDENCE_ITEMS]
            ],
            "requirements": [
                "只使用给定证据，不要编造。",
                "使用中文，简洁直接。",
                "优先输出 2 到 4 句短段落，或者 2 到 3 个要点。",
                "不要输出调试信息或提示词标签。",
                "如果证据不足，要明确说明信息不足。",
            ],
        }
        return json.dumps(
            {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是企业知识库助手。"
                            "回答必须严格基于给定证据，简洁、自然，适合业务同学直接阅读。"
                            "不要复述提示词，也不要展开无关内容。"
                        ),
                    },
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                "temperature": 0.2,
                "stream": stream,
            },
            ensure_ascii=False,
        ).encode("utf-8")

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 24) -> Generator[str, None, None]:
        for start in range(0, len(text), chunk_size):
            yield text[start : start + chunk_size]

    def _degraded_result(self, retrieval_results: list[RetrievalResult], reason: str) -> GenerationResult:
        return GenerationResult(
            content=f"{self._fallback_notice()}\n\n{self._mock_generate(retrieval_results)}",
            provider="mock-fallback",
            degraded=True,
            fallback_reason=reason,
        )

    def _stream_degraded_result(
        self,
        retrieval_results: list[RetrievalResult],
        reason: str,
    ) -> Generator[StreamGenerationEvent, None, None]:
        yield StreamGenerationEvent(
            type="metadata",
            provider="mock-fallback",
            degraded=True,
            fallback_reason=reason,
        )
        fallback_text = f"{self._fallback_notice()}\n\n{self._mock_generate(retrieval_results)}"
        for chunk in self._chunk_text(fallback_text):
            yield StreamGenerationEvent(
                type="delta",
                content=chunk,
                provider="mock-fallback",
                degraded=True,
                fallback_reason=reason,
            )

    @staticmethod
    def _fallback_notice() -> str:
        return "提示：当前模型服务不可用，以下内容为基于知识库证据生成的降级摘要。"

    @staticmethod
    def _format_fallback_reason(exc: Exception) -> str:
        return f"模型调用失败：{type(exc).__name__}: {exc}"

    @staticmethod
    def _missing_configuration_reason(runtime: dict[str, object]) -> str:
        missing: list[str] = []
        if not runtime.get("base_url"):
            missing.append("未配置模型服务地址")
        if not settings.llm_api_key:
            missing.append("未配置模型 API Key")
        detail = "、".join(missing) if missing else "模型服务配置不完整"
        return f"模型降级：{detail}"
