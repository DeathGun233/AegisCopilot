import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ChatComposer } from "../components/chat/ChatComposer";
import { MessageList } from "../components/chat/MessageList";
import { useAppContext } from "../context/AppContext";
import { fetchJson, streamChat } from "../lib/api";

const starterPrompts = [
  "What is the employee leave process?",
  "What should be checked before a production release?",
  "Summarize the travel reimbursement process.",
  "What should a cross-border ecommerce company watch for in personal data protection?",
];

const scenarioCards = [
  {
    title: "Policy QA",
    description: "Ask grounded questions about internal policy, process, and standards.",
    prompt: "What is the employee leave process?",
  },
  {
    title: "Process summary",
    description: "Turn scattered evidence into a more structured operational summary.",
    prompt: "Summarize the travel reimbursement process.",
  },
  {
    title: "Release checklist",
    description: "Convert release questions into a practical pre-launch checklist.",
    prompt: "What should be checked before a production release?",
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
    setStreamStatus("Connecting to the model...");
    setQuery("");
    setCitationMap((current) => ({ ...current, [assistantId]: [] }));

    let nextConversationId = conversationId || null;
    let answer = "";

    try {
      await streamChat({ query: trimmed, conversationId }, {
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
      });

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
          message.id === assistantId ? { ...message, content: "The model request failed. Please try again." } : message,
        ),
      );
      setStreamStatus(error.message || "The model request failed.");
    } finally {
      setIsStreaming(false);
    }
  }

  return (
    <div className="page chat-page">
      <header className="page-header">
        <div>
          <span className="page-kicker">AegisCopilot / Chat</span>
          <h1>{currentConversation?.title || "New conversation"}</h1>
        </div>
      </header>

      <section className="chat-hero">
        <div className="hero-copy">
          <span className="hero-pill">RAG Assistant</span>
          <h2>Turn questions into grounded answers</h2>
          <p>Ask structured questions, search internal evidence, and stream concise responses for real business use.</p>
        </div>

        <ChatComposer
          query={query}
          onQueryChange={setQuery}
          onSubmit={handleSendMessage}
          isStreaming={isStreaming}
          streamStatus={streamStatus}
          starterPrompts={starterPrompts}
        />

        <div className="scenario-grid">
          {scenarioCards.map((item) => (
            <button key={item.title} type="button" className="scenario-tile" onClick={() => setQuery(item.prompt)}>
              <strong>{item.title}</strong>
              <p>{item.description}</p>
              <small>{item.prompt}</small>
            </button>
          ))}
        </div>
      </section>

      <section className="thread-panel">
        <div className="panel-head">
          <div>
            <span className="panel-kicker">Conversation</span>
            <h3>Thread</h3>
          </div>
          <span className={isStreaming ? "status-dot live" : "status-dot"}>Streaming</span>
        </div>
        <MessageList messages={messages} citationMap={citationMap} />
      </section>
    </div>
  );
}
