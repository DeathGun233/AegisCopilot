import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ChatComposer } from "../components/chat/ChatComposer";
import { MessageList } from "../components/chat/MessageList";
import { useAppContext } from "../context/AppContext";
import { fetchJson, streamChat } from "../lib/api";

const starterPrompts = [
  "员工请假流程是什么？",
  "生产发布前需要检查什么？",
  "请总结差旅报销流程。",
  "跨境电商公司在个人信息保护方面要注意什么？",
];

const scenarioCards = [
  {
    title: "制度问答",
    description: "围绕企业制度、流程和规范发起基于知识库的提问。",
    prompt: "员工请假流程是什么？",
  },
  {
    title: "流程总结",
    description: "把分散证据整理成更结构化的操作结论。",
    prompt: "请总结差旅报销流程。",
  },
  {
    title: "发布检查",
    description: "把发布类问题转成上线前可执行的检查清单。",
    prompt: "生产发布前需要检查什么？",
  },
];

export function ChatPage() {
  const navigate = useNavigate();
  const { conversationId } = useParams();
  const { conversations, refreshConversations, refreshStats } = useAppContext();
  const [messages, setMessages] = useState([]);
  const [query, setQuery] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamStatus, setStreamStatus] = useState("");
  const [citationMap, setCitationMap] = useState({});
  const threadEndRef = useRef(null);

  const currentConversation = useMemo(
    () => conversations.find((item) => item.id === conversationId) || null,
    [conversations, conversationId],
  );

  useEffect(() => {
    if (conversationId && currentConversation) {
      setMessages(currentConversation.messages || []);
      setCitationMap({});
      setStreamStatus("");
      return;
    }
    if (!conversationId) {
      setMessages([]);
      setCitationMap({});
      setStreamStatus("");
      return;
    }

    fetchJson(`/conversations/${conversationId}`)
      .then((data) => {
        setMessages(data.conversation.messages || []);
      })
      .catch(() => {
        navigate("/chat");
      });
  }, [conversationId, currentConversation, navigate]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      threadEndRef.current?.scrollIntoView({
        block: "end",
        behavior: messages.length > 1 ? "smooth" : "auto",
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [messages, isStreaming, streamStatus]);

  async function handleSendMessage(event) {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || isStreaming) {
      return;
    }

    const assistantId = `assistant-${Date.now()}`;
    setMessages((current) => [
      ...current,
      { id: `user-${Date.now()}`, role: "user", content: trimmed },
      { id: assistantId, role: "assistant", content: "" },
    ]);
    setIsStreaming(true);
    setStreamStatus("正在连接模型...");
    setQuery("");
    setCitationMap((current) => ({ ...current, [assistantId]: [] }));

    let nextConversationId = conversationId || null;
    let answer = "";

    try {
      await streamChat(
        { query: trimmed, conversationId },
        {
          onConversation(payload) {
            nextConversationId = payload.conversation_id;
          },
          onStatus(payload) {
            setStreamStatus(payload.message);
          },
          onDelta(payload) {
            answer += payload.content;
            setMessages((current) =>
              current.map((message) => (message.id === assistantId ? { ...message, content: answer } : message)),
            );
          },
          onDone(payload) {
            if (payload.task?.citations?.length) {
              setCitationMap((current) => ({
                ...current,
                [assistantId]: payload.task.citations,
              }));
            }
          },
        },
      );

      const nextConversations = await refreshConversations();
      await refreshStats();
      if (nextConversationId) {
        navigate(`/chat/${nextConversationId}`, { replace: true });
        const synced = nextConversations.find((item) => item.id === nextConversationId);
        if (synced) {
          setMessages(synced.messages || []);
        }
      }
    } catch (error) {
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantId ? { ...message, content: "模型请求失败，请稍后重试。" } : message,
        ),
      );
      setStreamStatus(error.message || "模型请求失败");
    } finally {
      setIsStreaming(false);
    }
  }

  return (
    <div className="page chat-page">
      <header className="page-header">
        <div>
          <span className="page-kicker">AegisCopilot / 对话</span>
          <h1>{currentConversation?.title || "新对话"}</h1>
        </div>
      </header>

      <section className="chat-shell">
        <section className="thread-panel thread-panel--chat">
          <div className="panel-head chat-thread-head">
            <div>
              <span className="panel-kicker">当前会话</span>
              <h3>{currentConversation?.title || "新对话"}</h3>
            </div>
            <span className={isStreaming ? "status-dot live" : "status-dot"}>
              {isStreaming ? "正在流式回答" : messages.length ? `${messages.length} 条消息` : "等待你的第一个问题"}
            </span>
          </div>

          <div className="chat-thread-scroll">
            {messages.length ? (
              <MessageList messages={messages} citationMap={citationMap} />
            ) : (
              <div className="chat-empty-state">
                <div className="chat-empty-hero">
                  <span className="hero-pill">RAG 智能问答</span>
                  <h2>把问题变成有依据的答案</h2>
                  <p>通过结构化提问、知识检索与流式生成，服务真实业务场景下的企业知识问答。</p>
                </div>

                <div className="chat-empty-grid">
                  {scenarioCards.map((item) => (
                    <button
                      key={item.title}
                      type="button"
                      className="scenario-tile"
                      onClick={() => setQuery(item.prompt)}
                    >
                      <strong>{item.title}</strong>
                      <p>{item.description}</p>
                      <small>{item.prompt}</small>
                    </button>
                  ))}
                </div>
              </div>
            )}
            <div ref={threadEndRef} />
          </div>
        </section>

        <div className="chat-dock">
          <ChatComposer
            className="chat-composer chat-composer--dock"
            query={query}
            onQueryChange={setQuery}
            onSubmit={handleSendMessage}
            isStreaming={isStreaming}
            streamStatus={streamStatus}
            starterPrompts={starterPrompts}
            rows={3}
          />
        </div>
      </section>
    </div>
  );
}
