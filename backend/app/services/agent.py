from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..config import settings
from ..models import AgentTask, Conversation, Intent, Message, MessageRole, WorkflowStep
from ..repositories import TaskRepository
from .generation_service import GenerationService
from .query_understanding import QueryUnderstandingResult, QueryUnderstandingService
from .retrieval import RetrievalService
from .tools import ToolService


@dataclass
class WorkflowContext:
    conversation: Conversation
    query: str
    understanding: QueryUnderstandingResult | None = None
    rewritten_query: str = ""
    expanded_queries: list[str] = field(default_factory=list)
    retrieval_queries: list[str] = field(default_factory=list)
    clarification_needed: bool = False
    clarification_reason: str = ""
    clarification_prompt: str = ""
    intent: Intent | None = None
    route_reason: str = ""
    retrieval_results: list = field(default_factory=list)
    answer: str = ""
    grounded: bool = False
    generation_provider: str = ""
    generation_degraded: bool = False
    generation_reason: str = ""
    trace: list[dict] = field(default_factory=list)


class AgentService:
    def __init__(
        self,
        *,
        retrieval: RetrievalService,
        tools: ToolService,
        tasks: TaskRepository,
        generation: GenerationService,
        query_understanding: QueryUnderstandingService,
    ) -> None:
        self.retrieval = retrieval
        self.tools = tools
        self.tasks = tasks
        self.generation = generation
        self.query_understanding = query_understanding

    def run(self, conversation: Conversation, query: str) -> tuple[Message, AgentTask]:
        context = WorkflowContext(conversation=conversation, query=query)
        steps = self._workflow_steps()

        self._understand_query(context)
        self._clarification_check(context)
        self._rewrite_query(context)
        self._expand_query(context)
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
        started_at = time.perf_counter()

        yield self._stream_status("正在分析问题上下文...", stage="understand_query", started_at=started_at)
        self._understand_query(context)
        yield self._stream_status("正在判断是否需要补充澄清...", stage="clarification_check", started_at=started_at)
        self._clarification_check(context)

        if context.clarification_needed:
            self._plan_response(context)
            yield self._stream_status("需要补充更多信息，正在生成澄清问题...", stage="clarification_response", started_at=started_at)
            context.answer = context.clarification_prompt
            yield {"type": "delta", "content": context.answer}
        else:
            yield self._stream_status("正在改写查询表达...", stage="query_rewrite", started_at=started_at)
            self._rewrite_query(context)
            yield self._stream_status("正在扩展检索表达...", stage="query_expand", started_at=started_at)
            self._expand_query(context)
            yield self._stream_status("正在识别问题意图...", stage="intent_route", started_at=started_at)
            self._detect_intent(context)

            if context.intent == Intent.chitchat:
                self._plan_response(context)
                yield self._stream_status("识别为轻量对话，正在直接回复...", stage="direct_reply", started_at=started_at)
                context.answer = self._greeting_answer()
                yield {"type": "delta", "content": context.answer}
            else:
                yield self._stream_status("正在执行混合检索...", stage="retrieve_context", started_at=started_at)
                self._retrieve_context(context)
                self._plan_response(context)

                supporting_results = self._select_supporting_results(context.retrieval_results)
                context.retrieval_results = supporting_results
                if supporting_results:
                    yield self._stream_status(
                        f"已完成检索，命中 {len(supporting_results)} 条高相关证据，正在生成回答...",
                        stage="generate_answer",
                        started_at=started_at,
                        hits=len(supporting_results),
                    )
                    stream = self.generation.stream_generate(
                        query=context.query,
                        intent=context.intent.value,
                        retrieval_results=supporting_results,
                        conversation_summary=self._summarize_history(context.conversation),
                    )
                    context.answer = ""
                    for item in stream:
                        if item.type == "metadata":
                            context.generation_provider = item.provider
                            context.generation_degraded = item.degraded
                            context.generation_reason = item.fallback_reason
                            if item.degraded:
                                yield self._stream_status(
                                    "模型调用失败，已切换为基于证据的降级摘要...",
                                    stage="generation_fallback",
                                    started_at=started_at,
                                    degraded=True,
                                )
                            continue
                        context.answer += item.content
                        yield {"type": "delta", "content": item.content}
                else:
                    yield self._stream_status(
                        "当前未检索到足够证据，正在整理说明...",
                        stage="insufficient_evidence",
                        started_at=started_at,
                        hits=0,
                    )
                    context.answer = self._insufficient_evidence_answer()
                    yield {"type": "delta", "content": context.answer}

        context.trace.append(
            {
                "step": WorkflowStep.tool_or_answer,
                "answer_preview": context.answer[:180],
                "generation_provider": context.generation_provider or self.generation.provider,
                "generation_degraded": context.generation_degraded,
                "generation_reason": context.generation_reason,
            }
        )
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
            provider=context.generation_provider or self.generation.provider,
        )

    @staticmethod
    def _workflow_steps() -> list[WorkflowStep]:
        return [
            WorkflowStep.clarification_check,
            WorkflowStep.query_rewrite,
            WorkflowStep.query_expand,
            WorkflowStep.intent_route,
            WorkflowStep.retrieve_context,
            WorkflowStep.plan_response,
            WorkflowStep.tool_or_answer,
            WorkflowStep.response_grounding_check,
            WorkflowStep.final_response,
        ]

    def _understand_query(self, context: WorkflowContext) -> None:
        context.understanding = self.query_understanding.analyze(context.conversation, context.query)

    def _clarification_check(self, context: WorkflowContext) -> None:
        understanding = context.understanding or self.query_understanding.analyze(context.conversation, context.query)
        context.clarification_needed = understanding.needs_clarification
        context.clarification_reason = understanding.clarification_reason
        context.clarification_prompt = understanding.clarification_prompt
        context.trace.append(
            {
                "step": WorkflowStep.clarification_check,
                "needs_clarification": context.clarification_needed,
                "clarification_reason": context.clarification_reason,
                "clarification_prompt": context.clarification_prompt,
                "history_topic": understanding.history_topic,
            }
        )

    def _rewrite_query(self, context: WorkflowContext) -> None:
        understanding = context.understanding or self.query_understanding.analyze(context.conversation, context.query)
        context.rewritten_query = understanding.rewritten_query or context.query
        context.trace.append(
            {
                "step": WorkflowStep.query_rewrite,
                "original_query": context.query,
                "rewritten_query": context.rewritten_query,
            }
        )

    def _expand_query(self, context: WorkflowContext) -> None:
        understanding = context.understanding or self.query_understanding.analyze(context.conversation, context.query)
        context.expanded_queries = understanding.expanded_queries
        context.retrieval_queries = understanding.retrieval_queries or [context.rewritten_query or context.query]
        context.trace.append(
            {
                "step": WorkflowStep.query_expand,
                "retrieval_queries": context.retrieval_queries,
                "expanded_queries": context.expanded_queries,
            }
        )

    def _detect_intent(self, context: WorkflowContext) -> None:
        understanding = context.understanding or self.query_understanding.analyze(context.conversation, context.query)
        context.intent = understanding.intent
        context.route_reason = understanding.route_reason
        context.trace.append(
            {
                "step": WorkflowStep.intent_route,
                "intent": context.intent,
                "route_reason": context.route_reason,
            }
        )

    def _retrieve_context(self, context: WorkflowContext) -> None:
        retrieval_settings = self.retrieval.get_runtime_settings()
        if context.clarification_needed or context.intent == Intent.chitchat:
            context.retrieval_results = []
            context.trace.append(
                {
                    "step": WorkflowStep.retrieve_context,
                    "hits": 0,
                    "strategy": retrieval_settings.strategy.value,
                    "top_k": retrieval_settings.top_k,
                    "candidate_k": retrieval_settings.candidate_k,
                    "retrieval_queries": context.retrieval_queries,
                    "sources": [],
                }
            )
            return

        primary_query = context.rewritten_query or context.query
        variant_queries = [item for item in context.retrieval_queries if item.lower() != primary_query.lower()]
        context.retrieval_results = self.tools.knowledge_search(primary_query, variant_queries)
        context.trace.append(
            {
                "step": WorkflowStep.retrieve_context,
                "hits": len(context.retrieval_results),
                "strategy": retrieval_settings.strategy.value,
                "top_k": retrieval_settings.top_k,
                "candidate_k": retrieval_settings.candidate_k,
                "retrieval_queries": context.retrieval_queries,
                "sources": [item.source for item in context.retrieval_results],
                "score_preview": [
                    {
                        "source": item.display_source,
                        "score": item.score,
                        "keyword_score": item.keyword_score,
                        "semantic_score": item.semantic_score,
                        "semantic_source": item.semantic_source,
                        "rerank_score": item.rerank_score,
                        "matched_query": item.matched_query,
                        "query_variant": item.query_variant,
                    }
                    for item in context.retrieval_results[:4]
                ],
            }
        )

    def _plan_response(self, context: WorkflowContext) -> None:
        strategy = "direct_reply"
        if context.clarification_needed:
            strategy = "clarification_prompt"
        elif context.intent == Intent.task:
            strategy = "tool_augmented_summary"
        elif context.intent == Intent.knowledge_qa:
            strategy = "grounded_knowledge_answer"
        context.trace.append(
            {
                "step": WorkflowStep.plan_response,
                "strategy": strategy,
                "use_citations": context.intent != Intent.chitchat and not context.clarification_needed,
                "retrieval_hits": len(context.retrieval_results),
            }
        )

    def _tool_or_answer(self, context: WorkflowContext) -> None:
        if context.clarification_needed:
            context.answer = context.clarification_prompt
        elif context.intent == Intent.chitchat:
            context.answer = self._greeting_answer()
        elif context.retrieval_results:
            supporting_results = self._select_supporting_results(context.retrieval_results)
            result = self.generation.generate(
                query=context.query,
                intent=context.intent.value,
                retrieval_results=supporting_results,
                conversation_summary=self._summarize_history(context.conversation),
            )
            context.answer = result.content
            context.retrieval_results = supporting_results
            context.generation_provider = result.provider
            context.generation_degraded = result.degraded
            context.generation_reason = result.fallback_reason
        else:
            context.answer = self._insufficient_evidence_answer()
        context.trace.append(
            {
                "step": WorkflowStep.tool_or_answer,
                "answer_preview": context.answer[:180],
                "generation_provider": context.generation_provider or self.generation.provider,
                "generation_degraded": context.generation_degraded,
                "generation_reason": context.generation_reason,
            }
        )

    def _grounding_check(self, context: WorkflowContext) -> None:
        score = context.retrieval_results[0].score if context.retrieval_results else 0.0
        context.grounded = (
            score >= settings.min_grounding_score
            or context.intent == Intent.chitchat
            or context.clarification_needed
        )
        if not context.grounded and context.intent != Intent.chitchat and not context.clarification_needed:
            context.answer = (
                "我检索到少量相关内容，但证据还不足以支撑可靠结论。"
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
        return "当前知识库里还没有足够证据支撑这个问题的回答。"

    @staticmethod
    def _stream_status(
        message: str,
        *,
        stage: str,
        started_at: float,
        **extra: object,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "type": "status",
            "message": message,
            "stage": stage,
            "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
        }
        payload.update(extra)
        return payload
