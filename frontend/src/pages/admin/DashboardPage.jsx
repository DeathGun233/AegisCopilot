import { useEffect, useState } from "react";
import { useAppContext } from "../../context/AppContext";
import { formatDateTime, truncate } from "../../lib/format";

const defaultPreviewQuery = "员工请假流程是什么？";

function formatPercent(value) {
  return `${Math.round((Number(value) || 0) * 100)}%`;
}

function statusLabel(status) {
  if (status === "ok") {
    return "正常";
  }
  if (status === "warning") {
    return "需关注";
  }
  if (status === "error") {
    return "异常";
  }
  return status || "-";
}

export function DashboardPage() {
  const {
    bulkReindexDocuments,
    currentUser,
    documents,
    fetchRetrievalSettings,
    modelCatalog,
    previewRetrieval,
    refreshSystemStatus,
    setGlobalNotice,
    stats,
    systemStatus,
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
  const [bulkLoading, setBulkLoading] = useState("");
  const [bulkResult, setBulkResult] = useState(null);
  const [statusRefreshing, setStatusRefreshing] = useState(false);

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

  async function handleRefreshStatus() {
    setStatusRefreshing(true);
    try {
      await refreshSystemStatus();
    } catch (error) {
      setGlobalNotice(error.message || "系统状态刷新失败");
    } finally {
      setStatusRefreshing(false);
    }
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

  async function handleBulkReindex(mode) {
    setBulkLoading(mode);
    try {
      const result = await bulkReindexDocuments(mode);
      setBulkResult(result);
      if (result.failed_documents.length) {
        setGlobalNotice(`批量补建完成，但有 ${result.failed_documents.length} 篇文档失败`);
      } else if (mode === "all") {
        setGlobalNotice(`全量重建任务已排队，共 ${result.queued_documents} 篇文档`);
      } else if (mode === "outdated_embeddings") {
        setGlobalNotice(`版本升级任务已排队，共 ${result.queued_documents} 篇文档`);
      } else {
        setGlobalNotice(`向量补建任务已排队，共 ${result.queued_documents} 篇文档`);
      }
    } catch (error) {
      setGlobalNotice(error.message || "批量补建失败");
    } finally {
      setBulkLoading("");
    }
  }

  const missingEmbeddingDocuments = documents.filter((item) => !item.embedding_ready);
  const weightTotal = Number(form.keyword_weight) + Number(form.semantic_weight);
  const effectiveKeywordWeight = weightTotal > 0 ? Number(form.keyword_weight) / weightTotal : 0.5;
  const effectiveSemanticWeight = weightTotal > 0 ? Number(form.semantic_weight) / weightTotal : 0.5;
  const candidateRatio =
    Number(form.top_k) > 0 ? (Number(form.candidate_k) / Number(form.top_k)).toFixed(1) : "-";

  return (
    <div className="admin-content">
      <section className="dashboard-hero">
        <div>
          <span className="hero-pill">运营总览</span>
          <h2>检索与向量化后台</h2>
          <p>
            这里集中看知识库的向量覆盖率、检索参数、向量服务接入状态，以及一键补建老文档向量的执行入口。
          </p>
        </div>
      </section>

      <section className="metric-grid">
        <article className="metric-card">
          <span>知识文档</span>
          <strong>{stats?.documents ?? 0}</strong>
          <small>当前纳入管理的文档总数。</small>
        </article>
        <article className="metric-card">
          <span>索引片段</span>
          <strong>{stats?.indexed_chunks ?? 0}</strong>
          <small>当前可参与检索的片段数。</small>
        </article>
        <article className="metric-card">
          <span>已向量化文档</span>
          <strong>{stats?.embedded_documents ?? 0}</strong>
          <small>至少存在一个真实向量片段的文档数。</small>
        </article>
        <article className="metric-card">
          <span>已向量化片段</span>
          <strong>{stats?.embedded_chunks ?? 0}</strong>
          <small>已经写入真实向量的片段数。</small>
        </article>
        <article className="metric-card">
          <span>待补建文档</span>
          <strong>{stats?.pending_embedding_documents ?? 0}</strong>
          <small>仍缺少真实向量的历史文档数。</small>
        </article>
        <article className="metric-card">
          <span>版本落后文档</span>
          <strong>{stats?.stale_embedding_documents ?? 0}</strong>
          <small>向量版本与当前向量模型配置不一致。</small>
        </article>
        <article className="metric-card">
          <span>向量维度</span>
          <strong>{stats?.embedding_dimensions || "-"}</strong>
          <small>当前向量模型输出的向量维度。</small>
        </article>
      </section>

      <section className="admin-grid two-columns">
        <article className="panel-card">
          <div className="panel-head">
            <div>
              <span className="panel-kicker">系统状态</span>
              <h3>Readiness</h3>
            </div>
            <span className={`status-pill ${systemStatus?.ready ? "live" : "failed"}`}>
              {systemStatus?.ready ? "Ready" : "Degraded"}
            </span>
          </div>
          <div className="definition-list">
            <div>
              <span>数据库</span>
              <strong>
                {systemStatus?.providers?.database?.provider || "-"} /{" "}
                {statusLabel(systemStatus?.providers?.database?.status)}
              </strong>
            </div>
            <div>
              <span>向量层</span>
              <strong>
                {systemStatus?.providers?.vector?.provider || "-"} / {statusLabel(systemStatus?.providers?.vector?.status)}
              </strong>
            </div>
            <div>
              <span>Embedding</span>
              <strong>
                {systemStatus?.providers?.embedding?.provider || "-"} /{" "}
                {statusLabel(systemStatus?.providers?.embedding?.status)}
              </strong>
            </div>
            <div>
              <span>LLM</span>
              <strong>
                {systemStatus?.providers?.llm?.provider || "-"} / {statusLabel(systemStatus?.providers?.llm?.status)}
              </strong>
            </div>
          </div>
          <div className="inline-actions">
            <button
              type="button"
              className="secondary-action"
              disabled={statusRefreshing}
              onClick={handleRefreshStatus}
            >
              {statusRefreshing ? "刷新中..." : "刷新状态"}
            </button>
          </div>
        </article>

        <article className="panel-card">
          <div className="panel-head">
            <div>
              <span className="panel-kicker">向量数据库</span>
              <h3>Milvus 接入</h3>
            </div>
            <span className={`status-pill ${systemStatus?.providers?.vector?.provider === "milvus" ? "live" : ""}`}>
              {systemStatus?.providers?.vector?.provider === "milvus" ? "Milvus" : "Local"}
            </span>
          </div>
          <div className="definition-list compact">
            <div>
              <span>当前 provider</span>
              <strong>{systemStatus?.providers?.vector?.provider || "-"}</strong>
            </div>
            <div>
              <span>可选 provider</span>
              <strong>{systemStatus?.providers?.vector?.detail?.available_providers?.join(" / ") || "local / milvus"}</strong>
            </div>
            <div>
              <span>选择方式</span>
              <strong>
                {systemStatus?.providers?.vector?.detail?.selection_mode === "startup"
                  ? "启动环境变量"
                  : systemStatus?.providers?.vector?.detail?.selection_mode || "-"}
              </strong>
            </div>
            <div>
              <span>Milvus URI</span>
              <strong>{systemStatus?.providers?.vector?.detail?.uri || "未启用 Milvus"}</strong>
            </div>
            <div>
              <span>Collection</span>
              <strong>{systemStatus?.providers?.vector?.detail?.collection || "-"}</strong>
            </div>
          </div>
          {systemStatus?.providers?.vector?.provider !== "milvus" ? (
            <div className="global-notice">
              要启用 Milvus，请设置 `AEGIS_VECTOR_STORE_PROVIDER=milvus` 并重启后端；Docker Compose 默认会启动
              Milvus、etcd 和 MinIO。
            </div>
          ) : (
            <div className="global-notice">当前后端已经使用 Milvus 作为向量数据库。</div>
          )}
        </article>

        <article className="panel-card">
          <div className="panel-head">
            <div>
              <span className="panel-kicker">任务队列</span>
              <h3>索引任务</h3>
            </div>
          </div>
          <div className="definition-list">
            <div>
              <span>排队</span>
              <strong>{systemStatus?.document_tasks?.queued ?? 0}</strong>
            </div>
            <div>
              <span>运行中</span>
              <strong>{systemStatus?.document_tasks?.running ?? 0}</strong>
            </div>
            <div>
              <span>失败</span>
              <strong>{systemStatus?.document_tasks?.failed ?? 0}</strong>
            </div>
            <div>
              <span>活跃 worker</span>
              <strong>{systemStatus?.document_tasks?.active ?? 0}</strong>
            </div>
          </div>
        </article>
      </section>

      <section className="admin-grid two-columns">
        <article className="panel-card">
          <div className="panel-head">
            <div>
              <span className="panel-kicker">向量治理</span>
              <h3>批量补建入口</h3>
            </div>
          </div>
          <div className="definition-list compact">
            <div>
              <span>向量模型</span>
              <strong>{stats?.embedding_model || "-"}</strong>
            </div>
            <div>
              <span>向量服务提供方</span>
              <strong>{stats?.embedding_provider || "-"}</strong>
            </div>
            <div>
              <span>鉴权状态</span>
              <strong>{stats?.embedding_api_key_configured ? "已配置" : "未配置"}</strong>
            </div>
            <div>
              <span>待补建文档</span>
              <strong>{missingEmbeddingDocuments.length}</strong>
            </div>
            <div>
              <span>当前向量版本</span>
              <strong>{stats?.current_embedding_version || "-"}</strong>
            </div>
          </div>
          <div className="inline-actions">
            <button
              type="button"
              className="primary-action"
              disabled={bulkLoading === "missing_embeddings" || !stats?.embedding_api_key_configured}
              onClick={() => handleBulkReindex("missing_embeddings")}
            >
              {bulkLoading === "missing_embeddings" ? "补建中..." : "仅补齐缺失向量"}
            </button>
            <button
              type="button"
              className="secondary-action"
              disabled={bulkLoading === "outdated_embeddings" || !stats?.embedding_api_key_configured}
              onClick={() => handleBulkReindex("outdated_embeddings")}
            >
              {bulkLoading === "outdated_embeddings" ? "升级中..." : "升级过期向量版本"}
            </button>
            <button
              type="button"
              className="secondary-action"
              disabled={bulkLoading === "all" || !stats?.embedding_api_key_configured}
              onClick={() => handleBulkReindex("all")}
            >
              {bulkLoading === "all" ? "重建中..." : "全量重建全部文档"}
            </button>
          </div>
          {!stats?.embedding_api_key_configured ? (
            <div className="global-notice">当前还没有配置向量服务 API Key，批量补建按钮会保持禁用。</div>
          ) : null}
          {bulkResult ? (
            <div className="detail-stack">
              <div className="definition-list">
                <div>
                  <span>本次模式</span>
                  <strong>
                    {bulkResult.mode === "all"
                      ? "全量重建"
                      : bulkResult.mode === "outdated_embeddings"
                        ? "升级过期向量版本"
                        : "仅补缺失向量"}
                  </strong>
                </div>
                <div>
                  <span>命中文档</span>
                  <strong>{bulkResult.requested_documents}</strong>
                </div>
                <div>
                  <span>已排队任务</span>
                  <strong>{bulkResult.queued_documents}</strong>
                </div>
                <div>
                  <span>跳过数量</span>
                  <strong>{bulkResult.skipped_documents}</strong>
                </div>
                <div>
                  <span>当前活跃任务</span>
                  <strong>{bulkResult.active_tasks}</strong>
                </div>
                <div>
                  <span>失败数量</span>
                  <strong>{bulkResult.failed_documents.length}</strong>
                </div>
              </div>
              {bulkResult.failed_documents.length ? (
                <div className="chunk-list">
                  {bulkResult.failed_documents.slice(0, 4).map((item) => (
                    <article key={item.document_id} className="chunk-card">
                      <strong>{item.title}</strong>
                      <p>{item.error}</p>
                    </article>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </article>

        <article className="panel-card">
          <div className="panel-head">
            <div>
              <span className="panel-kicker">覆盖情况</span>
              <h3>待补建文档</h3>
            </div>
          </div>
          <div className="chunk-list">
            {missingEmbeddingDocuments.length ? (
              missingEmbeddingDocuments.slice(0, 6).map((document) => (
                <article key={document.id} className="chunk-card">
                  <strong>{document.title}</strong>
                  <p>{document.embedding_label}</p>
                  <small>
                    已向量化 {document.embedded_chunk_count} / {document.chunk_count} 个片段
                  </small>
                </article>
              ))
            ) : (
              <div className="table-empty">当前所有已索引文档都已经补齐真实向量了。</div>
            )}
          </div>
        </article>
      </section>

      <section className="admin-grid two-columns">
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
              <span>向量模型</span>
              <strong>{stats?.embedding_model || "-"}</strong>
            </div>
            <div>
              <span>向量服务鉴权</span>
              <strong>{stats?.embedding_api_key_configured ? "已配置" : "未配置"}</strong>
            </div>
          </div>
        </article>

        <article className="panel-card">
          <div className="panel-head">
            <div>
              <span className="panel-kicker">参数提示</span>
              <h3>检索参数解读</h3>
            </div>
          </div>
          <div className="definition-list">
            <div>
              <span>有效关键词权重</span>
              <strong>{formatPercent(effectiveKeywordWeight)}</strong>
            </div>
            <div>
              <span>有效语义权重</span>
              <strong>{formatPercent(effectiveSemanticWeight)}</strong>
            </div>
            <div>
              <span>候选倍率</span>
              <strong>{candidateRatio} 倍</strong>
            </div>
            <div>
              <span>当前最小召回分</span>
              <strong>{Number(form.min_score).toFixed(2)}</strong>
            </div>
          </div>
          <div className="chunk-list">
            <article className="chunk-card">
              <strong>如何理解这些参数</strong>
              <p>
                `candidate_k` 越大，召回范围越广；`top_k` 越小，送给大模型的证据越精简。关键词和语义权重会先归一化再参与混合打分。
              </p>
            </article>
            <article className="chunk-card">
              <strong>当前向量策略</strong>
              <p>
                已有真实向量的片段优先使用向量相似度；老文档若还没补建，会自动回退到轻量语义打分，不会直接失效。
              </p>
            </article>
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
