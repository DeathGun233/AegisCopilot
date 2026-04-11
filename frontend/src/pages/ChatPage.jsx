import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ChatComposer } from "../components/chat/ChatComposer";
import { MessageList } from "../components/chat/MessageList";
import { useAppContext } from "../context/AppContext";
import { fetchJson, streamChat } from "../lib/api";

const starterPrompts = [
  "??????????",
  "????????????",
  "??????????",
  "?????????????????????",
];

const scenarioCards = [
  {
    title: "????",
    description: "???????????????????????",
    prompt: "??????????",
  },
  {
    title: "????",
    description: "??????????????????",
    prompt: "??????????",
  },
  {
    title: "????",
    description: "????????????????????",
    prompt: "????????????",
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
  const [streamMeta, setStreamMeta] = useState({ elapsedMs: 0, hits: null });
  const [streamWaitSeconds, setStreamWaitSeconds] = useState(0);
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
      setStreamMeta({ elapsedMs: 0, hits: null });
      return;
    }
    if (!conversationId) {
      setMessages([]);
      setCitationMap({});
      setStreamStatus("");
      setStreamMeta({ elapsedMs: 0, hits: null });
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

  useEffect(() => {
    if (!isStreaming) {
      setStreamWaitSeconds(0);
      return undefined;
    }

    const startedAt = window.Date.now();
    setStreamWaitSeconds(0);
    const timer = window.setInterval(() => {
      setStreamWaitSeconds(Math.floor((window.Date.now() - startedAt) / 1000));
    }, 1000);

    return () => window.clearInterval(timer);
  }, [isStreaming]);

  const streamStatusLabel = useMemo(() => {
    if (!streamStatus) {
      return "";
    }

    const details = [streamStatus];
    const elapsedSeconds = Math.max(streamWaitSeconds, Math.floor((streamMeta.elapsedMs || 0) / 1000));
    if (isStreaming && elapsedSeconds > 0) {
      details.push(`??? ${elapsedSeconds} ?`);
    }
    if (typeof streamMeta.hits === "number" && streamMeta.hits > 0) {
      details.push(`?? ${streamMeta.hits} ?`);
    }
    return details.join(" ? ");
  }, [isStreaming, streamMeta.elapsedMs, streamMeta.hits, streamStatus, streamWaitSeconds]);

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
    setStreamStatus("????????...");
    setStreamMeta({ elapsedMs: 0, hits: null });
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
            setStreamMeta({
              elapsedMs: payload.elapsed_ms ?? 0,
              hits: typeof payload.hits === "number" ? payload.hits : null,
            });
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
          message.id === assistantId ? { ...message, content: "?????????????" } : message,
        ),
      );
      setStreamStatus(error.message || "??????");
      setStreamMeta({ elapsedMs: 0, hits: null });
    } finally {
      setIsStreaming(false);
    }
  }

  return (
    <div className="page chat-page">
      <header className="page-header">
        <div>
          <span className="page-kicker">AegisCopilot / ??</span>
          <h1>{currentConversation?.title || "???"}</h1>
        </div>
      </header>

      <section className="chat-shell">
        <section className="thread-panel thread-panel--chat">
          <div className="panel-head chat-thread-head">
            <div>
              <span className="panel-kicker">????</span>
              <h3>{currentConversation?.title || "???"}</h3>
            </div>
            <span className={isStreaming ? "status-dot live" : "status-dot"}>
              {isStreaming ? "??????" : messages.length ? `${messages.length} ???` : "?????????"}
            </span>
          </div>

          <div className="chat-thread-scroll">
            {messages.length ? (
              <MessageList messages={messages} citationMap={citationMap} />
            ) : (
              <div className="chat-empty-state">
                <div className="chat-empty-hero">
                  <span className="hero-pill">RAG ????</span>
                  <h2>???????????</h2>
                  <p>???????????????????????????????????</p>
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
            streamStatus={streamStatusLabel}
            starterPrompts={starterPrompts}
            rows={3}
          />
        </div>
      </section>
    </div>
  );
}
