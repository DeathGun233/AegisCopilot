import { useAppContext } from "../../context/AppContext";

export function DashboardPage() {
  const { currentUser, documents, modelCatalog, stats, users } = useAppContext();

  return (
    <div className="admin-content">
      <section className="dashboard-hero">
        <div>
          <span className="hero-pill">运营总览</span>
          <h2>后台运行概览</h2>
          <p>统一查看知识库规模、模型运行状态、用户角色和 Agent 任务情况。</p>
        </div>
      </section>

      <section className="metric-grid">
        <article className="metric-card">
          <span>知识文档</span>
          <strong>{stats?.documents ?? 0}</strong>
          <small>当前已纳入知识库管理的文档总数。</small>
        </article>
        <article className="metric-card">
          <span>索引片段</span>
          <strong>{stats?.indexed_chunks ?? 0}</strong>
          <small>当前可被检索层召回的片段数量。</small>
        </article>
        <article className="metric-card">
          <span>会话数量</span>
          <strong>{stats?.conversations ?? 0}</strong>
          <small>当前登录账号下的会话总数。</small>
        </article>
        <article className="metric-card">
          <span>任务数量</span>
          <strong>{stats?.tasks ?? 0}</strong>
          <small>当前账号累计产生的 Agent 任务记录。</small>
        </article>
      </section>

      <section className="admin-grid two-columns">
        <article className="panel-card">
          <div className="panel-head">
            <div>
              <span className="panel-kicker">知识快照</span>
              <h3>最近文档</h3>
            </div>
          </div>
          <div className="chunk-list">
            {documents.slice(0, 5).map((document) => (
              <article key={document.id} className="chunk-card">
                <strong>{document.title}</strong>
                <p>
                  {document.department} / {document.chunk_count || 0} 个片段 / {document.index_state_label}
                </p>
              </article>
            ))}
          </div>
        </article>

        <article className="panel-card">
          <div className="panel-head">
            <div>
              <span className="panel-kicker">运行状态</span>
              <h3>当前环境</h3>
            </div>
          </div>
          <div className="definition-list">
            <div>
              <span>当前用户</span>
              <strong>{currentUser?.name || "-"}</strong>
            </div>
            <div>
              <span>用户数量</span>
              <strong>{users.length}</strong>
            </div>
            <div>
              <span>模型提供方</span>
              <strong>{stats?.llm_provider || "-"}</strong>
            </div>
            <div>
              <span>当前模型</span>
              <strong>{modelCatalog?.active_model || stats?.llm_model || "-"}</strong>
            </div>
          </div>
        </article>
      </section>
    </div>
  );
}
