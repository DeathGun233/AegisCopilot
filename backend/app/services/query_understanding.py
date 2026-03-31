from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import Conversation, Intent, MessageRole
from .text import normalize_text, tokenize


@dataclass
class QueryUnderstandingResult:
    original_query: str
    normalized_query: str
    rewritten_query: str
    retrieval_queries: list[str] = field(default_factory=list)
    expanded_queries: list[str] = field(default_factory=list)
    intent: Intent = Intent.knowledge_qa
    route_reason: str = ""
    needs_clarification: bool = False
    clarification_reason: str = ""
    clarification_prompt: str = ""
    history_topic: str = ""


class QueryUnderstandingService:
    _GREETING_PATTERNS = ("hello", "hi", "你好", "在吗", "哈喽", "早上好", "下午好", "晚上好")
    _TASK_PATTERNS = ("总结", "汇总", "梳理", "整理", "清单", "步骤", "对比", "比较", "归纳", "提炼")
    _FOCUS_COMMANDS = ("总结", "汇总", "梳理", "整理", "归纳", "提炼", "对比", "比较", "清单", "列一下")
    _REFERENTIAL_PATTERNS = ("这个", "这个流程", "这个制度", "这个文档", "那个", "那个流程", "它", "上面", "上一条", "刚才")
    _GENERIC_PATTERNS = ("帮我看下", "帮我看看", "说一下", "讲讲", "总结一下", "整理一下", "分析一下", "展开说说")
    _QUESTION_FILLERS = ("是什么", "是啥", "是什么样", "怎么", "如何", "怎样", "哪些", "哪一些", "吗", "呢", "呀")
    _TOPIC_STOPWORDS = (
        "请",
        "帮我",
        "帮忙",
        "一下",
        "一下子",
        "我们",
        "公司",
        "想问",
        "我想问",
        "我想了解",
        "麻烦",
        "请问",
    )

    def analyze(self, conversation: Conversation | None, query: str) -> QueryUnderstandingResult:
        normalized_query = normalize_text(query)
        history_topic = self._extract_history_topic(conversation, normalized_query)
        intent, route_reason = self._detect_intent(normalized_query)
        rewritten_query = self._rewrite_query(normalized_query, history_topic, intent)

        needs_clarification, clarification_reason, clarification_prompt = self._needs_clarification(
            normalized_query,
            rewritten_query,
            history_topic,
            intent,
        )

        expanded_queries = [] if needs_clarification else self._expand_queries(rewritten_query, intent, history_topic)
        retrieval_queries = self._dedupe_queries([rewritten_query, *expanded_queries]) if not needs_clarification else []

        return QueryUnderstandingResult(
            original_query=query,
            normalized_query=normalized_query,
            rewritten_query=rewritten_query,
            retrieval_queries=retrieval_queries,
            expanded_queries=expanded_queries,
            intent=intent,
            route_reason=route_reason,
            needs_clarification=needs_clarification,
            clarification_reason=clarification_reason,
            clarification_prompt=clarification_prompt,
            history_topic=history_topic,
        )

    def _detect_intent(self, query: str) -> tuple[Intent, str]:
        compact_query = query.lower().replace(" ", "")
        if any(pattern in compact_query for pattern in self._GREETING_PATTERNS):
            return Intent.chitchat, "识别为寒暄或轻量闲聊，直接走对话回复链路。"
        if any(pattern in compact_query for pattern in self._TASK_PATTERNS):
            return Intent.task, "识别为总结、梳理、对比或步骤类问题，优先组织结构化答案。"
        return Intent.knowledge_qa, "默认走知识库问答链路，优先检索制度与流程证据。"

    def _rewrite_query(self, query: str, history_topic: str, intent: Intent) -> str:
        cleaned = query.strip()
        if not cleaned:
            return query

        if history_topic and self._is_context_dependent(cleaned):
            if any(keyword in cleaned for keyword in ("流程", "步骤")):
                return f"{history_topic}的流程和步骤是什么"
            if any(keyword in cleaned for keyword in ("总结", "梳理", "整理", "清单", "归纳", "提炼")):
                return f"请总结{history_topic}的关键要求和执行要点"
            if any(keyword in cleaned for keyword in ("材料", "资料", "凭证", "附件")):
                return f"{history_topic}需要准备哪些材料和凭证"
            return f"{history_topic} {self._strip_context_words(cleaned)}".strip()

        focus = self._extract_focus_phrase(cleaned)
        if intent == Intent.task and focus and focus != cleaned:
            return f"{focus}的关键要求和执行要点"
        return cleaned

    def _needs_clarification(
        self,
        query: str,
        rewritten_query: str,
        history_topic: str,
        intent: Intent,
    ) -> tuple[bool, str, str]:
        stripped = query.strip()
        token_count = len(tokenize(stripped))
        focus = self._extract_focus_phrase(rewritten_query)

        if not stripped or len(stripped) <= 1 or token_count <= 1:
            return (
                True,
                "问题过短，无法确定具体主题。",
                "我还不确定你想查哪一项制度或流程。可以直接说主题，例如“差旅报销流程”或“请假审批要求”。",
            )

        if self._is_context_dependent(stripped) and not history_topic:
            return (
                True,
                "问题依赖上文指代，但当前会话里没有足够参照对象。",
                "我还不确定你说的“这个”具体指哪份制度或流程。可以补一句主题名称，我再继续帮你查。",
            )

        if intent == Intent.task and len(focus) <= 4 and not history_topic:
            return (
                True,
                "任务型问题缺少明确主题。",
                "你希望我总结或整理哪一项内容？可以直接说制度名、流程名，或者贴出你想处理的主题。",
            )

        if any(word in stripped for word in ("对比", "比较")) and not re.search(r"[和与、/]", stripped) and not history_topic:
            return (
                True,
                "对比类问题缺少比较对象。",
                "你想对比哪两项内容？例如“对比出差报销和采购报销流程”。",
            )

        return False, "", ""

    def _expand_queries(self, rewritten_query: str, intent: Intent, history_topic: str) -> list[str]:
        focus = self._extract_focus_phrase(rewritten_query) or rewritten_query
        candidates: list[str] = []
        if focus != rewritten_query:
            candidates.append(focus)

        if any(keyword in rewritten_query for keyword in ("流程", "步骤", "审批")):
            candidates.append(f"{focus} 流程")
            candidates.append(f"{focus} 审批要求")
        elif any(keyword in rewritten_query for keyword in ("材料", "凭证", "附件", "条件")):
            candidates.append(f"{focus} 材料要求")
            candidates.append(f"{focus} 条件说明")
        elif intent == Intent.task:
            candidates.append(f"{focus} 关键要点")
            candidates.append(f"{focus} 执行要求")
        else:
            candidates.append(f"{focus} 制度要求")
            candidates.append(f"{focus} 适用范围")

        if history_topic and history_topic not in focus:
            candidates.append(history_topic)

        return self._dedupe_queries(candidates)

    def _extract_history_topic(self, conversation: Conversation | None, current_query: str) -> str:
        if conversation is None:
            return ""

        history_messages = list(conversation.messages or [])
        for preferred_role in (MessageRole.user, MessageRole.assistant):
            for message in reversed(history_messages):
                if message.role != preferred_role:
                    continue
                content = normalize_text(message.content)
                if not content:
                    continue
                if message.role == MessageRole.user and content == current_query:
                    continue
                if len(content) < 4:
                    continue
                candidate = self._extract_focus_phrase(content)
                if not candidate:
                    continue
                if message.role == MessageRole.assistant and candidate.startswith("依据"):
                    candidate = candidate.replace("依据", "", 1).strip("，。:： ")
                if candidate:
                    return candidate[:48]
        return ""

    def _extract_focus_phrase(self, query: str) -> str:
        cleaned = normalize_text(query)
        if not cleaned:
            return ""

        for word in self._TOPIC_STOPWORDS + self._GENERIC_PATTERNS + self._FOCUS_COMMANDS:
            cleaned = cleaned.replace(word, " ")
        for word in self._QUESTION_FILLERS:
            cleaned = cleaned.replace(word, " ")

        cleaned = self._strip_context_words(cleaned)
        cleaned = re.sub(r"[，。！？；：,.!?/]+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned[:64]

    def _is_context_dependent(self, query: str) -> bool:
        stripped = query.strip()
        if any(word in stripped for word in self._REFERENTIAL_PATTERNS):
            return True
        return stripped in self._GENERIC_PATTERNS

    def _strip_context_words(self, query: str) -> str:
        cleaned = query
        for word in self._REFERENTIAL_PATTERNS:
            cleaned = cleaned.replace(word, " ")
        return re.sub(r"\s+", " ", cleaned).strip()

    @staticmethod
    def _dedupe_queries(queries: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for item in queries:
            normalized = normalize_text(item)
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(normalized)
        return deduped
