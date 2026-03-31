from __future__ import annotations

import json
from pathlib import Path

from ..config import settings
from ..models import EvaluationCase, EvaluationRun, Message, MessageRole
from ..repositories import ConversationRepository
from .agent import AgentService


class EvaluationService:
    def __init__(self, agent: AgentService, conversations: ConversationRepository, owner_id: str) -> None:
        self.agent = agent
        self.conversations = conversations
        self.owner_id = owner_id

    def run(self) -> EvaluationRun:
        dataset_path = Path(__file__).resolve().parents[3] / "evaluation" / "sample_qa.json"
        payload = json.loads(dataset_path.read_text(encoding="utf-8"))
        cases = [EvaluationCase(**item) for item in payload]
        details: list[dict] = []
        answer_count = 0
        citation_hit = 0
        keyword_hit = 0

        for case in cases:
            conversation = self.conversations.create(title=case.question[:24], owner_id=self.owner_id)
            self.conversations.append_message(
                conversation.id,
                Message(role=MessageRole.user, content=case.question),
            )
            reply, task = self.agent.run(conversation, case.question)
            answer_count += int(bool(reply.content))
            if any(case.expected_document in citation.document_title for citation in task.citations):
                citation_hit += 1
            if any(keyword in reply.content for keyword in case.expected_keywords):
                keyword_hit += 1
            details.append(
                {
                    "case_id": case.id,
                    "question": case.question,
                    "answer": reply.content,
                    "citations": [citation.document_title for citation in task.citations],
                }
            )

        total = len(cases) or 1
        run = EvaluationRun(
            cases=len(cases),
            answer_rate=round(answer_count / total, 3),
            citation_hit_rate=round(citation_hit / total, 3),
            keyword_hit_rate=round(keyword_hit / total, 3),
            details=details,
        )
        report_path = settings.reports_dir / f"{run.id}.json"
        report_path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
        return run
