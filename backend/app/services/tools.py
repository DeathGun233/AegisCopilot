from __future__ import annotations

from ..models import RetrievalResult
from .retrieval import RetrievalService


class ToolService:
    def __init__(self, retrieval: RetrievalService) -> None:
        self.retrieval = retrieval

    def knowledge_search(self, query: str, query_variants: list[str] | None = None) -> list[RetrievalResult]:
        return self.retrieval.search(query, query_variants=query_variants)

    def web_search_mock(self, query: str) -> dict[str, str]:
        return {
            "tool": "web_search_mock",
            "query": query,
            "summary": "External web search is not enabled in the MVP. Use this tool as an extension point.",
        }

    def ticket_summary(self, text: str) -> dict[str, str]:
        lines = [line.strip("- ").strip() for line in text.splitlines() if line.strip()]
        bullets = lines[:3]
        return {
            "tool": "ticket_summary",
            "summary": " / ".join(bullets) if bullets else "No ticket content supplied.",
        }
