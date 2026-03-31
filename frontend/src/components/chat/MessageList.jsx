function messageKey(message, index) {
  return message.id || `${message.role}-${index}`;
}

export function MessageList({ messages, citationMap }) {
  if (!messages.length) {
    return (
      <div className="empty-thread">
        <strong>从一个新问题开始</strong>
        <p>系统会结合知识库内容和当前模型，给出更有依据的回答与引用。</p>
      </div>
    );
  }

  return (
    <div className="message-thread">
      {messages.map((message, index) => (
        <article
          key={messageKey(message, index)}
          className={message.role === "user" ? "message-card user" : "message-card assistant"}
        >
          <div className="message-meta">
            <span className="message-role">{message.role === "user" ? "用户" : "助手"}</span>
          </div>
          <div className="message-content">
            <p>{message.content}</p>
          </div>
          {message.role === "assistant" && citationMap[message.id]?.length ? (
            <div className="citation-row">
              {citationMap[message.id].map((item) => (
                <span key={item.chunk_id} className="citation-pill">
                  {item.display_source}
                </span>
              ))}
            </div>
          ) : null}
        </article>
      ))}
    </div>
  );
}
