from __future__ import annotations

import json

from app.models import RetrievalResult
from app.services.agent import AgentService
from app.services.generation_service import GenerationService


def _result(index: int, score: float) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=f"chunk-{index}",
        document_id="doc-policy",
        document_title="Policy Guide",
        text=f"policy evidence section {index}",
        score=score,
        source=f"Policy Guide#chunk-{index}",
    )


def test_agent_keeps_enough_supporting_results_for_broad_policy_answers() -> None:
    results = [_result(index, score) for index, score in enumerate([0.9, 0.7, 0.62, 0.55, 0.52, 0.5], start=1)]

    selected = AgentService._select_supporting_results(results)

    assert [item.chunk_id for item in selected] == [
        "chunk-1",
        "chunk-2",
        "chunk-3",
        "chunk-4",
        "chunk-5",
        "chunk-6",
    ]


def test_generation_payload_includes_more_than_three_evidence_items() -> None:
    results = [_result(index, 0.8) for index in range(1, 7)]

    payload = GenerationService._build_payload(
        query="summarize policy conditions",
        intent="knowledge_qa",
        retrieval_results=results,
        conversation_summary="",
        model="test-model",
        stream=False,
    )
    request_body = json.loads(payload.decode("utf-8"))
    user_prompt = json.loads(request_body["messages"][1]["content"])

    assert [item["text"] for item in user_prompt["evidence"]] == [
        "policy evidence section 1",
        "policy evidence section 2",
        "policy evidence section 3",
        "policy evidence section 4",
        "policy evidence section 5",
        "policy evidence section 6",
    ]
