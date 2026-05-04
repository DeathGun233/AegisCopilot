from __future__ import annotations

from types import SimpleNamespace

from app.models import EvaluationCase, Message, MessageRole, RetrievalResult
from app.repositories import ConversationRepository
from app.services.evaluation import EvaluationService


class ScriptedAgent:
    def __init__(self, replies: list[tuple[str, list[RetrievalResult]]]) -> None:
        self.replies = replies
        self.index = 0

    def run(self, conversation, question: str):
        answer, citations = self.replies[self.index]
        self.index += 1
        return Message(role=MessageRole.assistant, content=answer), SimpleNamespace(citations=citations)


def test_logistics_evaluation_reports_retrieval_and_no_answer_metrics() -> None:
    matching_citation = RetrievalResult(
        chunk_id="chunk-germany-battery",
        document_id="doc-eu-ddp",
        document_title="Europe DDP Customs Rules",
        text="Germany DDP battery products require MSDS and UN38.3.",
        score=0.91,
        source="Europe DDP Customs Rules#chunk-0",
        metadata={
            "section_path": "Germany > Battery Products",
            "row_id": "row-germany-battery",
        },
    )
    unrelated_citation = RetrievalResult(
        chunk_id="chunk-france-liquid",
        document_id="doc-eu-ddp",
        document_title="Europe DDP Customs Rules",
        text="France DDP liquid products require separate review.",
        score=0.52,
        source="Europe DDP Customs Rules#chunk-1",
        metadata={"section_path": "France > Liquid Products", "row_id": "row-france-liquid"},
    )
    service = EvaluationService(
        ScriptedAgent(
            [
                ("需要 MSDS、UN38.3，纯电池不接。", [unrelated_citation, matching_citation]),
                ("知识库中没有找到可支持的答案。", []),
            ]
        ),
        ConversationRepository(),
        owner_id="admin",
    )
    cases = [
        EvaluationCase(
            id="logistics-001",
            question="德国 DDP 带电产品需要哪些清关资料？",
            expected_answer="需要 MSDS、UN38.3；纯电池不接。",
            expected_documents=["Europe DDP Customs Rules"],
            expected_sections=["Germany > Battery Products"],
            expected_table_rows=["row-germany-battery"],
            expected_keywords=["MSDS", "UN38.3"],
            country="DE",
            channel="DDP空派",
            product_category="带电",
            query_type="customs_requirement",
            doc_type="customs_rule",
        ),
        EvaluationCase(
            id="logistics-002",
            question="德国 DDP 是否可以发活体动物？",
            expected_answer="知识库没有答案时应拒答。",
            expected_documents=[],
            expected_keywords=[],
            query_type="no_answer",
            negative=True,
        ),
    ]

    run = service.run_cases(cases)

    assert run.recall_at_k == 1.0
    assert run.precision_at_k == 0.5
    assert run.mrr == 0.5
    assert run.citation_accuracy == 1.0
    assert run.no_answer_accuracy == 1.0
    assert run.table_exact_match == 1.0
    assert run.details[0]["expected_documents"] == ["Europe DDP Customs Rules"]
    assert run.details[0]["first_relevant_rank"] == 2
    assert run.details[0]["matched_table_rows"] == ["row-germany-battery"]
