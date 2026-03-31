from __future__ import annotations

from dataclasses import dataclass, field

from ..config import settings
from ..models import AgentTask, Conversation, Intent, Message, MessageRole, WorkflowStep
from ..repositories import TaskRepository
from .generation_service import GenerationService
from .retrieval import RetrievalService
from .tools import ToolService


@dataclass
class WorkflowContext:
    conversation: Conversation
    query: str
    intent: Intent | None = None
    route_reason: str = ""
    retrieval_results: list = field(default_factory=list)
    answer: str = ""
    grounded: bool = False
    trace: list[dict] = field(default_factory=list)


class AgentService:
    def __init__(
        self,
        *,
        retrieval: RetrievalService,
        tools: ToolService,
        tasks: TaskRepository,
        generation: GenerationService,
    ) -> None:
        self.retrieval = retrieval
        self.tools = tools
        self.tasks = tasks
        self.generation = generation

    def run(self, conversation: Conversation, query: str) -> tuple[Message, AgentTask]:
        context = WorkflowContext(conversation=conversation, query=query)
        steps = self._workflow_steps()

        self._detect_intent(context)
        self._retrieve_context(context)
        self._plan_response(context)
        self._tool_or_answer(context)
        self._grounding_check(context)
        reply = self._finalize(context)

        task = self._build_task(conversation, query, context, reply, steps)
        self.tasks.save(task)
        return reply, task

    def run_stream(self, conversation: Conversation, query: str):
        context = WorkflowContext(conversation=conversation, query=query)
        steps = self._workflow_steps()

        self._detect_intent(context)
        yield {"type": "status", "message": "正在识别问题意图..."}
        self._retrieve_context(context)
        yield {"type": "status", "message": "正在执行混合检索..."}
        self._plan_response(context)
        yield {"type": "status", "message": "正在生成回答..."}

        if context.intent == Intent.chitchat:
            context.answer = self._greeting_answer()
            yield {"type": "delta", "content": context.answer}
        else:
            supporting_results = self._select_supporting_results(context.retrieval_results)
            context.retrieval_results = supporting_results
            if supporting_results:
                stream = self.generation.stream_generate(
                    query=context.query,
                    intent=context.intent.value,
                    retrieval_results=supporting_results,
                    conversation_summary=self._summarize_history(context.conversation),
                )
                context.answer = ""
                for piece in stream:
                    context.answer += piece
                    yield {"type": "delta", "content": piece}
            else:
                context.answer = self._insufficient_evidence_answer()
                yield {"type": "delta", "content": context.answer}

        context.trace.append({"step": WorkflowStep.tool_or_answer, "answer_preview": context.answer[:180]})
        self._grounding_check(context)
        reply = self._finalize(context)
        task = self._build_task(conversation, query, context, reply, steps)
        self.tasks.save(task)
        yield {"type": "done", "reply": reply.model_dump(mode="json"), "task": task.model_dump(mode="json")}

    def _build_task(
        self,
        conversation: Conversation,
        query: str,
        context: WorkflowContext,
        reply: Message,
        steps: list[WorkflowStep],
    ) -> AgentTask:
        return AgentTask(
            user_id=conversation.owner_id,
            conversation_id=conversation.id,
            query=query,
            intent=context.intent or Intent.knowledge_qa,
            steps=steps,
            trace=context.trace,
            final_answer=reply.content,
            citations=context.retrieval_results,
            route_reason=context.route_reason,
            provider=self.generation.provider,
        )

    @staticmethod
    def _workflow_steps() -> list[WorkflowStep]:
        return [
            WorkflowStep.intent_detect,
            WorkflowStep.retrieve_context,
            WorkflowStep.plan_response,
            WorkflowStep.tool_or_answer,
            WorkflowStep.response_grounding_check,
            WorkflowStep.final_response,
        ]

    def _detect_intent(self, context: WorkflowContext) -> None:
        raw_query = context.query.lower()
        compact_query = raw_query.replace(" ", "")
        if any(word in compact_query for word in ["compare", "summary", "summarize", "对比", "总结", "整理"]):
            context.intent = Intent.task
            context.route_reason = "识别为总结、整理或对比类问题。"
        elif any(word in compact_query for word in ["hello", "hi", "你好", "在吗"]):
            context.intent = Intent.chitchat
            context.route_reason = "识别为寒暄类问题。"
        else:
            context.intent = Intent.knowledge_qa
            context.route_reason = "默认走知识库问答链路。"
        context.trace.append(
            {
                "step": WorkflowStep.intent_detect,
                "intent": context.intent,
                "route_reason": context.route_reason,
            }
        )

    def _retrieve_context(self, context: WorkflowContext) -> None:
        if context.intent == Intent.chitchat:
            context.retrieval_results = []
            retrieval_settings = self.retrieval.get_runtime_settings()
            context.trace.append(
                {
                    "step": WorkflowStep.retrieve_context,
                    "hits": 0,
                    "strategy": retrieval_settings.strategy.value,
                    "top_k": retrieval_settings.top_k,
                    "candidate_k": retrieval_settings.candidate_k,
                    "sources": [],
                }
            )
            return

        context.retrieval_results = self.tools.knowledge_search(context.query)
        retrieval_settings = self.retrieval.get_runtime_settings()
        context.trace.append(
            {
                "step": WorkflowStep.retrieve_context,
                "hits": len(context.retrieval_results),
                "strategy": retrieval_settings.strategy.value,
                "top_k": retrieval_settings.top_k,
                "candidate_k": retrieval_settings.candidate_k,
                "sources": [item.source for item in context.retrieval_results],
                "score_preview": [
                    {
                        "source": item.display_source,
                        "score": item.score,
                        "keyword_score": item.keyword_score,
                        "semantic_score": item.semantic_score,
                        "rerank_score": item.rerank_score,
                    }
                    for item in context.retrieval_results[:4]
                ],
            }
        )

    def _plan_response(self, context: WorkflowContext) -> None:
        strategy = "direct_reply"
        if context.intent == Intent.task:
            strategy = "tool_augmented_summary"
        elif context.intent == Intent.knowledge_qa:
            strategy = "grounded_knowledge_answer"
        context.trace.append(
            {
                "step": WorkflowStep.plan_response,
                "strategy": strategy,
                "use_citations": context.intent != Intent.chitchat,
                "retrieval_hits": len(context.retrieval_results),
            }
        )

    def _tool_or_answer(self, context: WorkflowContext) -> None:
        if context.intent == Intent.chitchat:
            context.answer = self._greeting_answer()
        elif context.retrieval_results:
            supporting_results = self._select_supporting_results(context.retrieval_results)
            context.answer = self.generation.generate(
                query=context.query,
                intent=context.intent.value,
                retrieval_results=supporting_results,
                conversation_summary=self._summarize_history(context.conversation),
            )
            context.retrieval_results = supporting_results
        else:
            context.answer = self._insufficient_evidence_answer()
        context.trace.append({"step": WorkflowStep.tool_or_answer, "answer_preview": context.answer[:180]})

    def _grounding_check(self, context: WorkflowContext) -> None:
        score = context.retrieval_results[0].score if context.retrieval_results else 0.0
        context.grounded = score >= settings.min_grounding_score or context.intent == Intent.chitchat
        if not context.grounded and context.intent != Intent.chitchat:
            context.answer = (
                "我检索到少量相关内容，但证据还不足以支持可靠结论。"
                "建议进一步缩小问题范围，或者补充更多内部资料。"
            )
        context.trace.append(
            {
                "step": WorkflowStep.response_grounding_check,
                "grounded": context.grounded,
                "top_score": score,
            }
        )

    def _finalize(self, context: WorkflowContext) -> Message:
        reply = Message(role=MessageRole.assistant, content=context.answer)
        context.trace.append({"step": WorkflowStep.final_response, "message_id": reply.id})
        return reply

    @staticmethod
    def _summarize_history(conversation: Conversation) -> str:
        relevant = [message.content for message in conversation.messages[-settings.max_history_messages :]]
        return " | ".join(relevant[-4:])

    @staticmethod
    def _select_supporting_results(results: list) -> list:
        if not results:
            return []
        top_score = results[0].score
        threshold = max(settings.min_grounding_score, top_score * 0.65)
        filtered = [item for item in results if item.score >= threshold]
        return filtered[:3] or results[:1]

    @staticmethod
    def _greeting_answer() -> str:
        return "你好，我是 AegisCopilot。你可以向我咨询企业制度、业务流程、产品文档或技术规范相关的问题。"

    @staticmethod
    def _insufficient_evidence_answer() -> str:
        return "当前知识库里还没有足够证据支持这个问题的回答。"
