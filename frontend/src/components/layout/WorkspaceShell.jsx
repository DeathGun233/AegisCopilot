import { useMemo, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useAppContext } from "../../context/AppContext";
import { formatDateTime, getConversationPreview, truncate } from "../../lib/format";

export function WorkspaceShell({ children }) {
  const navigate = useNavigate();
  const location = useLocation();
  const {
    conversations,
    createConversation,
    currentUser,
    deleteConversation,
    globalNotice,
    isAdmin,
    logout,
    modelCatalog,
    selectModel,
    setGlobalNotice,
    stats,
  } = useAppContext();
  const [keyword, setKeyword] = useState("");

  const primaryNav = useMemo(() => {
    const items = [{ to: "/chat", label: "聊天问答", hint: "基于知识库发起提问并获取带引用的回答" }];
    if (isAdmin) {
      items.push({ to: "/admin/overview", label: "管理后台", hint: "治理知识库、用户和评估任务" });
    }
    return items;
  }, [isAdmin]);

  const filteredConversations = useMemo(() => {
    const needle = keyword.trim().toLowerCase();
    if (!needle) {
      return conversations;
    }
    return conversations.filter((conversation) =>
      [conversation.title, ...(conversation.messages || []).map((item) => item.content)]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [conversations, keyword]);

  async function handleCreateConversation() {
    const conversation = await createConversation("新对话");
    navigate(`/chat/${conversation.id}`);
  }

  async function handleDeleteConversation(event, conversationId) {
    event.stopPropagation();
    await deleteConversation(conversationId);
    if (location.pathname === `/chat/${conversationId}`) {
      navigate("/chat");
    }
  }

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="workspace-shell">
      <aside className="left-rail">
        <div className="brand-block">
          <div className="brand-badge">AI</div>
          <div>
            <strong>AegisCopilot</strong>
            <p>企业知识库智能助手</p>
          </div>
        </div>

        <nav className="rail-nav">
          {primaryNav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                isActive || location.pathname.startsWith(item.to) ? "rail-nav-item active" : "rail-nav-item"
              }
            >
              <strong>{item.label}</strong>
              <small>{item.hint}</small>
            </NavLink>
          ))}
        </nav>

        <section className="rail-card launch-card">
          <div className="card-title-row">
            <span>快捷开始</span>
            <button type="button" className="text-link" onClick={handleCreateConversation}>
              新建
            </button>
          </div>
          <button type="button" className="launch-button" onClick={handleCreateConversation}>
            <span className="launch-icon">+</span>
            <div>
              <strong>发起新对话</strong>
              <small>为新的业务问题或知识查询开启一条独立会话。</small>
            </div>
          </button>
          {isAdmin ? (
            <button type="button" className="panel-shortcut" onClick={() => navigate("/admin/knowledge")}>
              进入知识库后台
            </button>
          ) : null}
        </section>

        <label className="search-card">
          <span>搜索会话</span>
          <input
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            placeholder="按标题或消息内容搜索"
          />
        </label>

        <section className="conversation-pane">
          <div className="section-head">
            <span>最近会话</span>
            <small>{filteredConversations.length}</small>
          </div>
          <div className="conversation-list">
            {filteredConversations.length ? (
              filteredConversations.map((conversation) => (
                <article
                  key={conversation.id}
                  className={
                    location.pathname === `/chat/${conversation.id}`
                      ? "conversation-item active"
                      : "conversation-item"
                  }
                  onClick={() => navigate(`/chat/${conversation.id}`)}
                >
                  <div className="conversation-copy">
                    <strong>{conversation.title || "新对话"}</strong>
                    <p>{truncate(getConversationPreview(conversation), 56)}</p>
                  </div>
                  <div className="conversation-actions">
                    <small>{formatDateTime(conversation.updated_at)}</small>
                    <button
                      type="button"
                      className="danger-text"
                      onClick={(event) => handleDeleteConversation(event, conversation.id)}
                    >
                      删除
                    </button>
                  </div>
                </article>
              ))
            ) : (
              <div className="table-empty">还没有历史会话，可以先从上方创建一个。</div>
            )}
          </div>
        </section>

        <div className="rail-footer">
          <div className="user-card">
            <div className="user-avatar">{(currentUser?.name || "A").slice(0, 1).toUpperCase()}</div>
            <div>
              <strong>{currentUser?.name || "未知用户"}</strong>
              <p>{isAdmin ? "管理员" : "成员"}</p>
            </div>
          </div>

          {modelCatalog ? (
            <label className="identity-switch">
              <span>当前模型</span>
              <select
                value={modelCatalog.active_model}
                onChange={(event) => selectModel(event.target.value).catch(console.error)}
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

          {stats ? (
            <div className="rail-stats">
              <span>{stats.documents} 篇文档</span>
              <span>{stats.conversations} 个会话</span>
              <span>{stats.tasks} 条任务</span>
            </div>
          ) : null}

          <button type="button" className="secondary-action" onClick={handleLogout}>
            退出登录
          </button>

          {globalNotice ? (
            <button type="button" className="global-notice" onClick={() => setGlobalNotice("")}>
              {globalNotice}
            </button>
          ) : null}
        </div>
      </aside>

      <div className="workspace-stage">{children}</div>
    </div>
  );
}
