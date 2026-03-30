import { useEffect, useMemo, useState } from "react";

const apiBase = "http://127.0.0.1:8002";

const navItems = [
  { id: "chat", label: "聊天工作台", hint: "RAG 智能问答" },
  { id: "knowledge", label: "管理后台", hint: "知识库与用户治理" },
  { id: "evaluation", label: "评估中心", hint: "离线效果验证" },
];

const starterPrompts = [
  "员工请假需要提前多久申请？",
  "生产发布前需要准备什么？",
  "请总结差旅报销流程。",
  "跨境电商公司在个人信息保护方面要注意哪些问题？",
];

const scenarioCards = [
  {
    title: "制度问答",
    description: "快速查询企业制度、流程规范和内部要求。",
    prompt: "员工请假需要提前多久申请？",
  },
  {
    title: "任务总结",
    description: "围绕知识库内容整理成结构化答案。",
    prompt: "请总结差旅报销流程。",
  },
  {
    title: "发布准备",
    description: "把发布类问题转换成可执行的检查清单。",
    prompt: "生产发布前需要准备什么？",
  },
];

async function fetchJson(path, options = {}, userId = "admin") {
  const response = await fetch(`${apiBase}${path}`, {
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": userId,
      ...(options.headers || {}),
    },
    ...options,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return response.json();
}

function formatTime(value) {
  if (!value) return "";
  return new Date(value).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function getPreview(conversation) {
  const latest = conversation.messages?.[conversation.messages.length - 1];
  return latest?.content || "从空白开始";
}

export function AppProductConsole() {
  const [activeSection, setActiveSection] = useState("chat");
  const [documents, setDocuments] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [users, setUsers] = useState([]);
  const [currentUserId, setCurrentUserId] = useState("admin");
  const [currentUser, setCurrentUser] = useState({
    name: "admin",
    role: "admin",
    email: "owner@aegis.local",
  });
  const [stats, setStats] = useState(null);
  const [modelCatalog, setModelCatalog] = useState(null);
  const [conversationId, setConversationId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [query, setQuery] = useState("");
  const [evaluation, setEvaluation] = useState(null);
  const [streamStatus, setStreamStatus] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [citationMap, setCitationMap] = useState({});
  const [conversationFilter, setConversationFilter] = useState("");
  const [knowledgeFilter, setKnowledgeFilter] = useState("");
  const [departmentFilter, setDepartmentFilter] = useState("all");
  const [indexFilter, setIndexFilter] = useState("all");
  const [adminNotice, setAdminNotice] = useState("");

  const isAdmin = currentUser?.role === "admin";

  async function refreshDashboard() {
    const [docsData, statsData, conversationsData, modelsData, usersData, meData] = await Promise.all([
      fetchJson("/documents", {}, currentUserId),
      fetchJson("/system/stats", {}, currentUserId),
      fetchJson("/conversations", {}, currentUserId),
      fetchJson("/models", {}, currentUserId),
      fetchJson("/users", {}, currentUserId),
      fetchJson("/users/me", {}, currentUserId),
    ]);

    const orderedConversations = [...conversationsData.conversations].sort(
      (left, right) => new Date(right.updated_at) - new Date(left.updated_at),
    );

    setDocuments(docsData.documents);
    setStats(statsData.stats);
    setModelCatalog(modelsData.catalog);
    setUsers(usersData.users);
    setCurrentUser(meData.user);
    setConversations(orderedConversations);

    const activeConversation = orderedConversations.find((item) => item.id === conversationId);
    if (activeConversation) {
      setMessages(activeConversation.messages || []);
      return;
    }

    if (orderedConversations.length) {
      const latest = orderedConversations[0];
      setConversationId(latest.id);
      setMessages(latest.messages || []);
    } else {
      setConversationId(null);
      setMessages([]);
    }
  }

  useEffect(() => {
    refreshDashboard().catch(console.error);
  }, [currentUserId]);

  const filteredConversations = useMemo(() => {
    const keyword = conversationFilter.trim().toLowerCase();
    if (!keyword) return conversations;
    return conversations.filter((conversation) =>
      [conversation.title, ...(conversation.messages || []).map((item) => item.content)]
        .join(" ")
        .toLowerCase()
        .includes(keyword),
    );
  }, [conversationFilter, conversations]);

  const departmentOptions = useMemo(
    () =>
      Array.from(
        new Set(documents.map((document) => document.department).filter(Boolean)),
      ).sort((left, right) => left.localeCompare(right, "zh-CN")),
    [documents],
  );

  const filteredDocuments = useMemo(() => {
    const keyword = knowledgeFilter.trim().toLowerCase();
    return documents.filter((document) => {
      const matchesKeyword = keyword
        ? [document.title, document.department, document.source_type]
            .filter(Boolean)
            .join(" ")
            .toLowerCase()
            .includes(keyword)
        : true;
      const matchesDepartment =
        departmentFilter === "all" ? true : document.department === departmentFilter;
      const matchesIndex =
        indexFilter === "all"
          ? true
          : indexFilter === "indexed"
            ? Boolean(document.indexed)
            : !document.indexed;
      return matchesKeyword && matchesDepartment && matchesIndex;
    });
  }, [departmentFilter, documents, indexFilter, knowledgeFilter]);

  const knowledgeStats = useMemo(() => {
    const indexedCount = documents.filter((document) => document.indexed).length;
    return {
      total: documents.length,
      indexed: indexedCount,
      pending: documents.length - indexedCount,
      departments: departmentOptions.length,
    };
  }, [departmentOptions.length, documents]);

  async function handleCreateConversation() {
    const data = await fetchJson(
      "/conversations",
      {
        method: "POST",
        body: JSON.stringify({ title: "新对话" }),
      },
      currentUserId,
    );
    setConversationId(data.conversation.id);
    setMessages([]);
    setCitationMap({});
    setStreamStatus("");
    setActiveSection("chat");
    await refreshDashboard();
  }

  async function handleDeleteConversation(targetId) {
    await fetchJson(`/conversations/${targetId}`, { method: "DELETE" }, currentUserId);
    if (targetId === conversationId) {
      setConversationId(null);
      setMessages([]);
      setCitationMap({});
      setStreamStatus("");
    }
    await refreshDashboard();
  }

  async function handleModelChange(event) {
    try {
      await fetchJson(
        "/models/select",
        {
          method: "POST",
          body: JSON.stringify({ model_id: event.target.value }),
        },
        currentUserId,
      );
      setAdminNotice("");
      await refreshDashboard();
    } catch {
      setAdminNotice("当前身份没有模型管理权限，请切换到管理员账号。");
    }
  }

  async function handleDeleteDocument(documentId) {
    try {
      await fetchJson(`/documents/${documentId}`, { method: "DELETE" }, currentUserId);
      setAdminNotice("文档已从知识库删除。");
      await refreshDashboard();
    } catch {
      setAdminNotice("当前身份没有删除权限，请切换到管理员账号。");
    }
  }

  async function handleUploadDocument(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    setAdminNotice("正在解析文档并建立索引...");

    const formData = new FormData();
    formData.append("file", file);

    const response = await fetch(`${apiBase}/documents/upload`, {
      method: "POST",
      headers: { "X-User-Id": currentUserId },
      body: formData,
    });

    if (!response.ok) {
      setAdminNotice(
        isAdmin ? "文档上传失败，请检查文件格式是否受支持。" : "当前身份没有上传权限。",
      );
      return;
    }

    await response.json();
    setAdminNotice(`文档已录入知识库：${file.name}`);
    await refreshDashboard();
    setActiveSection("knowledge");
    event.target.value = "";
  }

  async function handleSendMessage(event) {
    event.preventDefault();
    if (!query.trim() || isStreaming) return;

    const currentQuery = query.trim();
    const assistantId = `assistant-${Date.now()}`;

    setMessages((current) => [
      ...current,
      { id: `user-${Date.now()}`, role: "user", content: currentQuery },
      { id: assistantId, role: "assistant", content: "" },
    ]);
    setIsStreaming(true);
    setStreamStatus("正在连接模型...");
    setQuery("");

    try {
      const response = await fetch(`${apiBase}/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-User-Id": currentUserId,
        },
        body: JSON.stringify({ query: currentQuery, conversation_id: conversationId }),
      });

      if (!response.ok || !response.body) {
        throw new Error(`stream request failed: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let nextConversationId = conversationId;
      let finalTask = null;
      let streamedAnswer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() || "";

        for (const frame of frames) {
          if (!frame.startsWith("data: ")) continue;
          const payload = JSON.parse(frame.slice(6));

          if (payload.type === "conversation") {
            nextConversationId = payload.conversation_id;
            setConversationId(payload.conversation_id);
          }

          if (payload.type === "status") {
            setStreamStatus(payload.message);
          }

          if (payload.type === "delta") {
            streamedAnswer += payload.content;
            setMessages((current) =>
              current.map((message) =>
                message.id === assistantId ? { ...message, content: streamedAnswer } : message,
              ),
            );
          }

          if (payload.type === "done") {
            finalTask = payload.task;
          }
        }
      }

      if (finalTask?.citations?.length) {
        setCitationMap((current) => ({
          ...current,
          [assistantId]: finalTask.citations,
        }));
      }

      setConversationId(nextConversationId);
      await refreshDashboard();
    } catch (error) {
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantId
            ? { ...message, content: "连接模型失败，请稍后重试。" }
            : message,
        ),
      );
      setStreamStatus(error.message || "连接模型失败");
    } finally {
      setIsStreaming(false);
    }
  }

  function handleSelectConversation(conversation) {
    setConversationId(conversation.id);
    setMessages(conversation.messages || []);
    setCitationMap({});
    setStreamStatus("");
    setActiveSection("chat");
  }

  async function handleRunEvaluation() {
    const data = await fetchJson("/evaluate/run", { method: "POST" }, currentUserId);
    setEvaluation(data.run);
    setActiveSection("evaluation");
    await refreshDashboard();
  }

  const activeConversationTitle =
    conversations.find((item) => item.id === conversationId)?.title || "新对话";

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="brand-panel">
          <div className="brand-mark">AI</div>
          <div>
            <strong>AegisCopilot</strong>
            <p>企业知识库 RAG 助手</p>
          </div>
        </div>

        <div className="quick-start-card">
          <div className="quick-start-head">
            <span>快速开始</span>
            <button type="button" className="mini-link" onClick={handleCreateConversation}>
              新建
            </button>
          </div>
          <button type="button" className="quick-action" onClick={handleCreateConversation}>
            <span className="quick-action-icon">+</span>
            <div>
              <strong>新建对话</strong>
              <small>从空白开始一轮问答</small>
            </div>
          </button>
          <button
            type="button"
            className="admin-entry"
            onClick={() => setActiveSection("knowledge")}
          >
            进入管理后台
          </button>
        </div>

        <label className="search-panel">
          <span>搜索对话</span>
          <input
            value={conversationFilter}
            onChange={(event) => setConversationFilter(event.target.value)}
            placeholder="搜索标题或消息内容..."
          />
        </label>

        <nav className="nav-stack">
          {navItems.map((item) => (
            <button
              key={item.id}
              type="button"
              className={item.id === activeSection ? "nav-item active" : "nav-item"}
              onClick={() => setActiveSection(item.id)}
            >
              <strong>{item.label}</strong>
              <small>{item.hint}</small>
            </button>
          ))}
        </nav>

        <section className="conversation-section">
          <div className="section-label">
            <span>最近会话</span>
            <small>{filteredConversations.length}</small>
          </div>
          <div className="conversation-scroll">
            {filteredConversations.map((conversation) => (
              <article
                key={conversation.id}
                className={conversation.id === conversationId ? "conversation-card active" : "conversation-card"}
                onClick={() => handleSelectConversation(conversation)}
              >
                <div className="conversation-main">
                  <strong>{conversation.title || "新对话"}</strong>
                  <span>{getPreview(conversation)}</span>
                </div>
                <div className="conversation-meta">
                  <small>{formatTime(conversation.updated_at)}</small>
                  <button
                    type="button"
                    className="danger-link"
                    onClick={(event) => {
                      event.stopPropagation();
                      handleDeleteConversation(conversation.id).catch(console.error);
                    }}
                  >
                    删除
                  </button>
                </div>
              </article>
            ))}
          </div>
        </section>

        <div className="user-panel">
          <div className="avatar-dot">
            {(currentUser?.name || "A").slice(0, 1).toUpperCase()}
          </div>
          <div>
            <strong>{currentUser?.name || "admin"}</strong>
            <p>{currentUser?.role || "admin"} · demo account</p>
          </div>
        </div>

        <label className="model-picker">
          <span>当前身份</span>
          <select value={currentUserId} onChange={(event) => setCurrentUserId(event.target.value)}>
            {users.map((user) => (
              <option key={user.id} value={user.id}>
                {user.name} ({user.role})
              </option>
            ))}
          </select>
        </label>
      </aside>

      <main className="app-main">
        <header className="main-header">
          <div>
            <span className="eyebrow">
              {navItems.find((item) => item.id === activeSection)?.hint}
            </span>
            <h1>
              {activeSection === "chat"
                ? activeConversationTitle
                : navItems.find((item) => item.id === activeSection)?.label}
            </h1>
          </div>

          <div className="header-actions">
            {modelCatalog ? (
              <label className="model-picker">
                <span>模型</span>
                <select
                  value={modelCatalog.active_model}
                  onChange={handleModelChange}
                  disabled={!isAdmin}
                >
                  {modelCatalog.options.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}

            <button type="button" className="secondary-button" onClick={handleRunEvaluation}>
              运行评估
            </button>
          </div>
        </header>

        {stats ? (
          <section className="stats-grid">
            <article className="stat-card">
              <span>文档数</span>
              <strong>{stats.documents}</strong>
              <small>已录入知识文档</small>
            </article>
            <article className="stat-card">
              <span>Chunk 数</span>
              <strong>{stats.indexed_chunks}</strong>
              <small>已建立索引片段</small>
            </article>
            <article className="stat-card">
              <span>会话数</span>
              <strong>{stats.conversations}</strong>
              <small>历史问答与聊天记录</small>
            </article>
            <article className="stat-card">
              <span>当前模型</span>
              <strong>{stats.llm_model}</strong>
              <small>{stats.llm_provider}</small>
            </article>
          </section>
        ) : null}

        {activeSection === "chat" ? (
          <section className="chat-workspace">
            <div className="hero-panel">
              <span className="hero-badge">企业级 RAG 问答</span>
              <h2>把问题变成清晰答案</h2>
              <p>
                结合知识检索、引用溯源和流式生成，在一次对话中产出简洁可执行的回答。
              </p>
            </div>

            <form className="hero-composer" onSubmit={handleSendMessage}>
              <textarea
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="输入需要分析的问题，例如：生产发布前需要准备什么？"
                rows={4}
              />

              <div className="composer-toolbar">
                <div className="chip-row">
                  {starterPrompts.map((item) => (
                    <button
                      key={item}
                      type="button"
                      className="ghost-chip"
                      onClick={() => setQuery(item)}
                    >
                      {item}
                    </button>
                  ))}
                </div>

                <button type="submit" className="primary-button" disabled={isStreaming}>
                  {isStreaming ? "生成中..." : "发送"}
                </button>
              </div>

              {streamStatus ? <p className="stream-status">{streamStatus}</p> : null}
            </form>

            <div className="scenario-grid">
              {scenarioCards.map((item) => (
                <button
                  key={item.title}
                  type="button"
                  className="scenario-card"
                  onClick={() => setQuery(item.prompt)}
                >
                  <strong>{item.title}</strong>
                  <p>{item.description}</p>
                  <small>{item.prompt}</small>
                </button>
              ))}
            </div>

            <section className="message-stage">
              {messages.length ? (
                messages.map((message) => (
                  <article
                    key={message.id || `${message.role}-${message.content}`}
                    className={`message-row ${message.role}`}
                  >
                    <div className="message-card">
                      <span className="message-role">
                        {message.role === "user" ? "用户" : "助手"}
                      </span>
                      <p>{message.content}</p>
                    </div>
                    {message.role === "assistant" && citationMap[message.id]?.length ? (
                      <div className="message-sources">
                        {citationMap[message.id].map((item) => (
                          <span key={item.chunk_id} className="source-chip">
                            {item.display_source}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </article>
                ))
              ) : (
                <div className="empty-panel">
                  <strong>从一个新问题开始</strong>
                  <p>你可以先上传知识库文档，再围绕制度、流程、产品或合规问题发起多轮问答。</p>
                </div>
              )}
            </section>
          </section>
        ) : null}

        {activeSection === "knowledge" ? (
          <section className="admin-page">
            <div className="page-hero">
              <div>
                <span className="eyebrow">Knowledge Admin</span>
                <h2>知识库管理后台</h2>
                <p>统一管理文档录入、索引状态、用户身份和知识库清理动作。</p>
              </div>

              <div className="hero-stack">
                <label className="primary-button upload-trigger">
                  上传文档
                  <input
                    type="file"
                    accept=".txt,.md,.markdown,.pdf,.docx"
                    onChange={handleUploadDocument}
                    hidden
                    disabled={!isAdmin}
                  />
                </label>
                <div className="hero-note">
                  <strong>当前筛选结果</strong>
                  <span>{filteredDocuments.length} 篇文档正在展示</span>
                </div>
              </div>
            </div>

            {adminNotice ? <p className="upload-status">{adminNotice}</p> : null}

            <div className="evaluation-panels admin-stats">
              <article className="metric-card">
                <span>文档总数</span>
                <strong>{knowledgeStats.total}</strong>
                <small>当前知识库文档</small>
              </article>
              <article className="metric-card">
                <span>已索引</span>
                <strong>{knowledgeStats.indexed}</strong>
                <small>可参与检索问答</small>
              </article>
              <article className="metric-card">
                <span>待处理</span>
                <strong>{knowledgeStats.pending}</strong>
                <small>还未建立索引</small>
              </article>
              <article className="metric-card">
                <span>部门数</span>
                <strong>{knowledgeStats.departments}</strong>
                <small>当前已覆盖部门</small>
              </article>
            </div>

            <div className="evaluation-panels">
              {users.map((user) => (
                <article key={user.id} className="metric-card">
                  <span>用户</span>
                  <strong>{user.name}</strong>
                  <small>{user.role}</small>
                </article>
              ))}
            </div>

            <div className="knowledge-toolbar">
              <label className="search-panel">
                <span>搜索知识库</span>
                <input
                  value={knowledgeFilter}
                  onChange={(event) => setKnowledgeFilter(event.target.value)}
                  placeholder="搜索标题、部门或来源..."
                />
              </label>

              <label className="model-picker">
                <span>部门筛选</span>
                <select
                  className="filter-select"
                  value={departmentFilter}
                  onChange={(event) => setDepartmentFilter(event.target.value)}
                >
                  <option value="all">全部部门</option>
                  {departmentOptions.map((department) => (
                    <option key={department} value={department}>
                      {department}
                    </option>
                  ))}
                </select>
              </label>

              <label className="model-picker">
                <span>索引状态</span>
                <select
                  className="filter-select"
                  value={indexFilter}
                  onChange={(event) => setIndexFilter(event.target.value)}
                >
                  <option value="all">全部状态</option>
                  <option value="indexed">仅看已索引</option>
                  <option value="pending">仅看待处理</option>
                </select>
              </label>
            </div>

            <div className="admin-table-head">
              <span>文档</span>
              <span>部门</span>
              <span>索引状态</span>
              <span>来源</span>
              <span>操作</span>
            </div>

            <div className="admin-list">
              {filteredDocuments.length ? (
                filteredDocuments.map((document) => (
                  <article key={document.id} className="admin-row">
                    <div>
                      <strong>{document.title}</strong>
                      <small>{formatTime(document.indexed_at || document.created_at)}</small>
                    </div>
                    <span className="tag-chip">{document.department}</span>
                    <span className={document.indexed ? "status-chip online" : "status-chip idle"}>
                      {document.indexed ? document.indexed_label : "未索引"}
                    </span>
                    <span className="muted-text">
                      {document.source_type}
                      <br />
                      {document.chunk_count ?? 0} chunks
                    </span>
                    <button
                      type="button"
                      className="danger-button"
                      disabled={!isAdmin}
                      onClick={() => handleDeleteDocument(document.id).catch(console.error)}
                    >
                      删除
                    </button>
                  </article>
                ))
              ) : (
                <div className="table-empty">
                  <strong>没有符合条件的文档</strong>
                  <span>可以调整筛选条件，或上传新的知识库文档。</span>
                </div>
              )}
            </div>
          </section>
        ) : null}

        {activeSection === "evaluation" ? (
          <section className="admin-page">
            <div className="page-hero">
              <div>
                <span className="eyebrow">Evaluation</span>
                <h2>效果评估中心</h2>
                <p>用离线测试集验证回答率、引用命中率和关键词覆盖率，观察系统迭代效果。</p>
              </div>

              <button type="button" className="primary-button" onClick={handleRunEvaluation}>
                重新运行评估
              </button>
            </div>

            {evaluation ? (
              <div className="evaluation-panels">
                <article className="metric-card">
                  <span>测试样例</span>
                  <strong>{evaluation.cases}</strong>
                </article>
                <article className="metric-card">
                  <span>回答率</span>
                  <strong>{evaluation.answer_rate}</strong>
                </article>
                <article className="metric-card">
                  <span>引用命中率</span>
                  <strong>{evaluation.citation_hit_rate}</strong>
                </article>
                <article className="metric-card">
                  <span>关键词命中率</span>
                  <strong>{evaluation.keyword_hit_rate}</strong>
                </article>
              </div>
            ) : (
              <div className="empty-panel">
                <strong>还没有评估结果</strong>
                <p>点击右上角按钮运行一轮离线评估，系统会展示当前问答质量。</p>
              </div>
            )}
          </section>
        ) : null}
      </main>
    </div>
  );
}
