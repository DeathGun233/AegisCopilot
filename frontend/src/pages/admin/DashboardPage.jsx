import { useEffect, useState } from "react";
import { useAppContext } from "../../context/AppContext";
import { formatDateTime, truncate } from "../../lib/format";

const defaultPreviewQuery = "员工请假流程是什么？";

export function DashboardPage() {
  const {
    currentUser,
    documents,
    fetchRetrievalSettings,
    modelCatalog,
    previewRetrieval,
    setGlobalNotice,
    stats,
    updateRetrievalSettings,
    users,
  } = useAppContext();
  const [retrievalSettings, setRetrievalSettings] = useState(null);
  const [form, setForm] = useState({
    top_k: 5,
    candidate_k: 12,
    keyword_weight: 0.55,
    semantic_weight: 0.45,
    rerank_weight: 0.6,
    min_score: 0.08,
  });
  const [saving, setSaving] = useState(false);
  const [previewQuery, setPreviewQuery] = useState(defaultPreviewQuery);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewResults, setPreviewResults] = useState([]);
  const [previewUnderstanding, setPreviewUnderstanding] = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function bootstrapRetrievalPanel() {
      try {
        const settings = await fetchRetrievalSettings();
        if (cancelled) {
          return;
        }
        setRetrievalSettings(settings);
        setForm({
          top_k: settings.top_k,
          candidate_k: settings.candidate_k,
          keyword_weight: settings.keyword_weight,
          semantic_weight: settings.semantic_weight,
          rerank_weight: settings.rerank_weight,
          min_score: settings.min_score,
        });
        const preview = await previewRetrieval(defaultPreviewQuery, settings.top_k);
        if (!cancelled) {
          setPreviewResults(preview.results);
          setPreviewUnderstanding(preview.understanding);
        }
      } catch (error) {
        if (!cancelled) {
          setGlobalNotice(error.message || "检索配置加载失败");
        }
      }
    }

    bootstrapRetrievalPanel();
    return () => {
      cancelled = true;
    };
  }, [fetchRetrievalSettings, previewRetrieval, setGlobalNotice]);

  function updateForm(key, value) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function handleSaveSettings(event) {
    event.preventDefault();
    setSaving(true);
    try {
      const payload = {
        top_k: Number(form.top_k),
        candidate_k: Number(form.candidate_k),
        keyword_weight: Number(form.keyword_weight),
        semantic_weight: Number(form.semantic_weight),
        rerank_weight: Number(form.rerank_weight),
        min_score: Number(form.min_score),
      };
      const settings = await updateRetrievalSettings(payload);
      setRetrievalSettings(settings);
      setGlobalNotice("检索参数已更新");
      const preview = await previewRetrieval(previewQuery, settings.top_k);
      setPreviewResults(preview.results);
      setPreviewUnderstanding(preview.understanding);
    } catch (error) {
      setGlobalNotice(error.message || "检索参数保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function handlePreview(event) {
    event.preventDefault();
    setPreviewLoading(true);
    try {
      const preview = await previewRetrieval(previewQuery, Number(form.top_k));
      setPreviewResults(preview.results);
      setPreviewUnderstanding(preview.understanding);
    } catch (error) {
      setGlobalNotice(error.message || "检索预览失败");
    } finally {
      setPreviewLoading(false);
    }
  }

  return (
    <div className="admin-content">
      <section className="dashboard-hero">
        <div>
          <span className="hero-pill">运营总览</span>
          <h2>后台运行概览</h2>
          <p>集中查看知识库规模、模型运行状态、向量召回接入情况，以及当前检索链路的关键参数。</p>
        </div>
      </section>

      <section className="metric-grid">
        <article className="metric-card">
          <span>知识文档</span>
          <strong>{stats?.documents ?? 0}</strong>
          <small>当前纳入知识库管理的文档总数。</small>
        </article>
        <article className="metric-card">
          <span>索引片段</span>
          <strong>{stats?.indexed_chunks ?? 0}</strong>
          <small>当前可被检索命中的文档片段数量。</small>
        </article>
        <article className="metric-card">
          <span>已向量化片段</span>
          <strong>{stats?.embedded_chunks ?? 0}</strong>
          <small>已经写入真实 embedding 的片段数量。</small>
        </article>
        <article className="metric-card">
          <span>检索 top-k</span>
          <strong>{stats?.retrieval_top_k ?? "-"}</strong>
          <small>最终返回给生成模型的证据条数上限。</small>
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
              <span>生成模型提供方</span>
              <strong>{stats?.llm_provider || "-"}</strong>
            </div>
            <div>
              <span>当前生成模型</span>
              <strong>{modelCatalog?.active_model || stats?.llm_model || "-"}</strong>
            </div>
            <div>
              <span>Embedding 模型</span>
              <strong>{stats?.embedding_model || "-"}</strong>
            </div>
            <div>
              <span>Embedding 鉴权</span>
              <strong>{stats?.embedding_api_key_configured ? "已配置" : "未配置"}</strong>
            </div>
          </div>
        </article>
      </section>

      <section className="admin-grid two-columns">
        <article className="panel-card">
          <div className="panel-head">
            <div>
              <span className="panel-kicker">检索调参</span>
              <h3>混合召回设置</h3>
            </div>
          </div>

          <form className="definition-list" onSubmit={handleSaveSettings}>
            <label className="toolbar-field">
              <span>最终返回 top-k</span>
              <input
                type="number"
                min="1"
                max="10"
                value={form.top_k}
                onChange={(event) => updateForm("top_k", event.target.value)}
              />
            </label>
            <label className="toolbar-field">
              <span>候选召回数</span>
              <input
                type="number"
                min="1"
                max="40"
                value={form.candidate_k}
                onChange={(event) => updateForm("candidate_k", event.target.value)}
              />
            </label>
            <label className="toolbar-field">
              <span>关键词权重</span>
              <input
                type="number"
                min="0"
                step="0.05"
                value={form.keyword_weight}
                onChange={(event) => updateForm("keyword_weight", event.target.value)}
              />
            </label>
            <label className="toolbar-field">
              <span>语义权重</span>
              <input
                type="number"
                min="0"
                step="0.05"
                value={form.semantic_weight}
                onChange={(event) => updateForm("semantic_weight", event.target.value)}
              />
            </label>
            <label className="toolbar-field">
              <span>重排强度</span>
              <input
                type="number"
                min="0"
                step="0.05"
                value={form.rerank_weight}
                onChange={(event) => updateForm("rerank_weight", event.target.value)}
              />
            </label>
            <label className="toolbar-field">
              <span>最小召回分</span>
              <input
                type="number"
                min="0"
                max="1"
                step="0.01"
                value={form.min_score}
                onChange={(event) => updateForm("min_score", event.target.value)}
              />
            </label>

            <div className="inline-actions">
              <button type="submit" className="primary-action" disabled={saving}>
                {saving ? "保存中..." : "保存检索参数"}
              </button>
            </div>
          </form>
        </article>

        <article className="panel-card">
          <div className="panel-head">
            <div>
              <span className="panel-kicker">检索预览</span>
              <h3>命中片段调试</h3>
            </div>
          </div>

          <form className="detail-stack" onSubmit={handlePreview}>
            <label className="toolbar-field">
              <span>测试问题</span>
              <textarea
                className="dashboard-preview-textarea"
                value={previewQuery}
                onChange={(event) => setPreviewQuery(event.target.value)}
                rows={3}
              />
            </label>
            <div className="inline-actions">
              <button type="submit" className="secondary-action" disabled={previewLoading}>
                {previewLoading ? "预览中..." : "执行检索预览"}
              </button>
            </div>
          </form>

          {previewUnderstanding ? (
            <div className="definition-list">
              <div>
                <span>识别意图</span>
                <strong>{previewUnderstanding.intent}</strong>
              </div>
              <div>
                <span>路由原因</span>
                <strong>{previewUnderstanding.route_reason}</strong>
              </div>
              <div>
                <span>改写后的查询</span>
                <strong>{previewUnderstanding.rewritten_query || "-"}</strong>
              </div>
              <div>
                <span>历史主题</span>
                <strong>{previewUnderstanding.history_topic || "-"}</strong>
              </div>
            </div>
          ) : null}

          {previewUnderstanding?.retrieval_queries?.length ? (
            <div className="chunk-list">
              <article className="chunk-card">
                <strong>本次检索表达</strong>
                <p>{previewUnderstanding.retrieval_queries.join(" / ")}</p>
                <small>
                  扩展表达：
                  {previewUnderstanding.expanded_queries?.length
                    ? previewUnderstanding.expanded_queries.join(" / ")
                    : "无"}
                </small>
              </article>
            </div>
          ) : null}

          {previewUnderstanding?.needs_clarification ? (
            <div className="table-empty">{previewUnderstanding.clarification_prompt}</div>
          ) : null}

          <div className="chunk-list">
            {previewResults.length ? (
              previewResults.map((item) => (
                <article key={item.chunk_id} className="chunk-card">
                  <strong>{item.display_source}</strong>
                  <p>{truncate(item.text, 140)}</p>
                  <small>
                    总分 {item.score} / 关键词 {item.keyword_score} / 语义 {item.semantic_score} / 重排{" "}
                    {item.rerank_score}
                  </small>
                  <small>
                    语义来源 {item.semantic_source} / 命中查询 {item.matched_query || "-"} / 变体{" "}
                    {item.query_variant}
                  </small>
                </article>
              ))
            ) : (
              <div className="table-empty">还没有检索预览结果，可以先执行一次测试。</div>
            )}
          </div>
        </article>
      </section>

      {retrievalSettings ? (
        <section className="panel-card">
          <div className="panel-head">
            <div>
              <span className="panel-kicker">检索摘要</span>
              <h3>当前检索链路配置</h3>
            </div>
            <small>{formatDateTime(new Date().toISOString())}</small>
          </div>
          <div className="definition-list">
            <div>
              <span>策略</span>
              <strong>{retrievalSettings.strategy}</strong>
            </div>
            <div>
              <span>top-k</span>
              <strong>{retrievalSettings.top_k}</strong>
            </div>
            <div>
              <span>候选数</span>
              <strong>{retrievalSettings.candidate_k}</strong>
            </div>
            <div>
              <span>关键词权重</span>
              <strong>{retrievalSettings.keyword_weight}</strong>
            </div>
            <div>
              <span>语义权重</span>
              <strong>{retrievalSettings.semantic_weight}</strong>
            </div>
            <div>
              <span>重排强度</span>
              <strong>{retrievalSettings.rerank_weight}</strong>
            </div>
          </div>
        </section>
      ) : null}
    </div>
  );
}
