from __future__ import annotations

import json
from pathlib import Path

from ..config import settings
from ..models import EvaluationCase, EvaluationRun, Message, MessageRole
from ..repositories import ConversationRepository
from .agent import AgentService


class EvaluationService:
    def __init__(
        self,
        agent: AgentService,
        conversations: ConversationRepository,
        owner_id: str,
        retrieval=None,
    ) -> None:
        self.agent = agent
        self.conversations = conversations
        self.owner_id = owner_id
        self.retrieval = retrieval

    def run(self) -> EvaluationRun:
        evaluation_dir = Path(__file__).resolve().parents[3] / "evaluation"
        logistics_path = evaluation_dir / "logistics_qa.json"
        dataset_path = logistics_path if logistics_path.exists() else evaluation_dir / "sample_qa.json"
        payload = json.loads(dataset_path.read_text(encoding="utf-8"))
        cases = [EvaluationCase(**item) for item in payload]
        return self.run_cases(cases)

    def run_cases(self, cases: list[EvaluationCase]) -> EvaluationRun:
        details: list[dict] = []
        answer_count = 0
        citation_hit = 0
        keyword_hit = 0
        recall_sum = 0.0
        precision_sum = 0.0
        reciprocal_rank_sum = 0.0
        citation_accuracy_count = 0
        no_answer_cases = 0
        no_answer_hits = 0
        table_cases = 0
        table_hits = 0
        version_cases = 0
        version_hits = 0
        positive_cases = 0

        for case in cases:
            raw_retrieval_results = self._run_retrieval(case)
            conversation = self.conversations.create(title=case.question[:24], owner_id=self.owner_id)
            self.conversations.append_message(
                conversation.id,
                Message(role=MessageRole.user, content=case.question),
            )
            reply, task = self.agent.run(conversation, case.question)
            if not raw_retrieval_results:
                raw_retrieval_results = list(getattr(task, "retrieval_results", []) or task.citations)
            retrieval_hits = [item for item in raw_retrieval_results if item.result_type != "context"]
            retrieval_contexts = [item for item in raw_retrieval_results if item.result_type == "context"]
            answer_count += int(bool(reply.content))
            expected_documents = self._expected_documents(case)
            relevant_ranks = [
                index
                for index, citation in enumerate(retrieval_hits, start=1)
                if self._citation_matches(case, citation)
            ]
            matched_table_rows = [
                str(citation.metadata.get("row_id"))
                for citation in retrieval_hits
                if citation.metadata.get("row_id") in set(case.expected_table_rows)
            ]
            answer_citation_match = any(self._citation_matches(case, citation) for citation in task.citations)

            if expected_documents and any(
                expected_document in citation.document_title
                for expected_document in expected_documents
                for citation in task.citations
            ):
                citation_hit += 1
            if any(keyword in reply.content for keyword in case.expected_keywords):
                keyword_hit += 1
            if case.negative:
                no_answer_cases += 1
                if not task.citations and self._looks_like_no_answer(reply.content):
                    no_answer_hits += 1
            else:
                positive_cases += 1
                recall_sum += 1.0 if relevant_ranks else 0.0
                precision_sum += len(relevant_ranks) / max(len(retrieval_hits), 1)
                reciprocal_rank_sum += 1 / relevant_ranks[0] if relevant_ranks else 0.0
                citation_accuracy_count += 1 if relevant_ranks else 0
                if case.expected_table_rows:
                    table_cases += 1
                    if set(case.expected_table_rows) <= set(matched_table_rows):
                        table_hits += 1
                if case.effective_date:
                    version_cases += 1
                    if any(
                        self._citation_matches(case, item)
                        and item.metadata.get("effective_date") == case.effective_date
                        for item in retrieval_hits
                    ):
                        version_hits += 1
            details.append(
                {
                    "case_id": case.id,
                    "question": case.question,
                    "answer": reply.content,
                    "citations": [citation.document_title for citation in task.citations],
                    "retrieval_results": [item.document_title for item in retrieval_hits],
                    "expected_answer": case.expected_answer,
                    "expected_documents": expected_documents,
                    "expected_sections": case.expected_sections,
                    "expected_table_rows": case.expected_table_rows,
                    "matched_table_rows": matched_table_rows,
                    "first_relevant_rank": relevant_ranks[0] if relevant_ranks else None,
                    "answer_citation_match": answer_citation_match,
                    "retrieval_hit_count": len(retrieval_hits),
                    "retrieval_context_count": len(retrieval_contexts),
                    "negative": case.negative,
                }
            )

        total = len(cases) or 1
        positive_total = positive_cases or 1
        positive_details = [item for item in details if not item.get("negative")]
        run = EvaluationRun(
            cases=len(cases),
            answer_rate=round(answer_count / total, 3),
            citation_hit_rate=round(citation_hit / total, 3),
            keyword_hit_rate=round(keyword_hit / total, 3),
            recall_at_k=round(recall_sum / positive_total, 3),
            precision_at_k=round(precision_sum / positive_total, 3),
            mrr=round(reciprocal_rank_sum / positive_total, 3),
            citation_accuracy=round(
                sum(1 for item in positive_details if item.get("answer_citation_match")) / positive_total,
                3,
            ),
            retrieval_citation_accuracy=round(citation_accuracy_count / positive_total, 3),
            answer_citation_accuracy=round(
                sum(1 for item in positive_details if item.get("answer_citation_match")) / positive_total,
                3,
            ),
            no_answer_accuracy=round(no_answer_hits / (no_answer_cases or 1), 3),
            table_exact_match=round(table_hits / (table_cases or 1), 3),
            version_accuracy=round(version_hits / (version_cases or 1), 3) if version_cases else 0.0,
            details=details,
        )
        report_path = settings.reports_dir / f"{run.id}.json"
        report_path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
        return run

    def _run_retrieval(self, case: EvaluationCase) -> list:
        if self.retrieval is None:
            return []
        return list(self.retrieval.search(case.question))

    @staticmethod
    def _expected_documents(case: EvaluationCase) -> list[str]:
        documents = list(case.expected_documents)
        if case.expected_document and case.expected_document not in documents:
            documents.append(case.expected_document)
        return documents

    @classmethod
    def _citation_matches(cls, case: EvaluationCase, citation) -> bool:
        expected_documents = cls._expected_documents(case)
        document_match = not expected_documents or any(
            expected_document in citation.document_title for expected_document in expected_documents
        )
        section_path = str(citation.metadata.get("section_path", ""))
        section_match = not case.expected_sections or any(
            expected_section in section_path for expected_section in case.expected_sections
        )
        chunk_match = not case.expected_chunks or citation.chunk_id in set(case.expected_chunks)
        row_match = not case.expected_table_rows or citation.metadata.get("row_id") in set(case.expected_table_rows)
        return document_match and section_match and chunk_match and row_match

    @staticmethod
    def _looks_like_no_answer(answer: str) -> bool:
        normalized = answer.strip().lower()
        if not normalized:
            return True
        no_answer_markers = ("没有找到", "无法回答", "无答案", "not found", "cannot answer", "no answer")
        return any(marker in normalized for marker in no_answer_markers)
