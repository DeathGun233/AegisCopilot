import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAppContext } from "../../context/AppContext";
import { formatDateTime, truncate } from "../../lib/format";

const emptyFilters = {
  q: "",
  department: "",
  source_type: "",
  index_state: "",
  tag: "",
  sort_by: "updated_desc",
};

function sourceLabel(document) {
  return document.source_label?.split(" / ")[0] || document.source_type || "-";
}

function isTaskActive(task) {
  return task && (task.status === "pending" || task.status === "running");
}

export function KnowledgePage() {
  const navigate = useNavigate();
  const {
    deleteDocument,
    documents,
    fetchUploadTask,
    queryDocuments,
    reindexDocument,
    setGlobalNotice,
    uploadDocumentFile,
  } = useAppContext();
  const [filters, setFilters] = useState(emptyFilters);
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState("");
  const [latestTask, setLatestTask] = useState(null);

  const filterOptions = useMemo(() => {
    const departments = [...new Set(documents.map((item) => item.department).filter(Boolean))].sort();
    const sourceTypes = [...new Set(documents.map((item) => item.source_type).filter(Boolean))].sort();
    const tags = [...new Set(documents.flatMap((item) => item.tags || []).filter(Boolean))].sort();
    return { departments, sourceTypes, tags };
  }, [documents]);

  const summary = useMemo(() => {
    const total = rows.length;
    const indexed = rows.filter((item) => item.index_state === "indexed").length;
    const failed = rows.filter((item) => item.index_state === "failed").length;
    const pending = rows.filter((item) => item.index_state === "pending" || item.index_state === "indexing").length;
    const stale = rows.filter((item) => item.embedding_stale).length;
    return { total, indexed, failed, pending, stale };
  }, [rows]);

  useEffect(() => {
    let cancelled = false;

    async function loadRows() {
      setLoading(true);
      try {
        const data = await queryDocuments(filters);
        if (!cancelled) {
          setRows(data);
        }
      } catch (error) {
        if (!cancelled) {
          setGlobalNotice(error.message || "知识库列表加载失败");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    loadRows();
    return () => {
      cancelled = true;
    };
  }, [filters, queryDocuments, setGlobalNotice]);

  useEffect(() => {
    if (!latestTask || !isTaskActive(latestTask)) {
      return undefined;
    }

    const timer = window.setInterval(async () => {
      try {
        const [taskResponse, rowsResponse] = await Promise.all([
          fetchUploadTask(latestTask.id),
          queryDocuments(filters),
        ]);
        setLatestTask(taskResponse.task);
        setRows(rowsResponse);
        if (!isTaskActive(taskResponse.task)) {
          const title = taskResponse.task.document_title || "当前文档";
          if (taskResponse.task.status === "succeeded") {
            setGlobalNotice(`《${title}》后台索引已完成，共 ${taskResponse.task.chunks_created} 个片段。`);
          } else if (taskResponse.task.status === "failed") {
            setGlobalNotice(taskResponse.task.error || `《${title}》索引失败`);
          }
          window.clearInterval(timer);
        }
      } catch {
        window.clearInterval(timer);
      }
    }, 2500);

    return () => window.clearInterval(timer);
  }, [fetchUploadTask, filters, latestTask, queryDocuments, setGlobalNotice]);

  function updateFilter(key, value) {
    setFilters((current) => ({ ...current, [key]: value }));
  }

  async function handleUpload(event) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    setBusyAction(`upload:${file.name}`);
    setGlobalNotice(`正在导入 ${file.name}，后台会继续完成索引。`);
    try {
      const result = await uploadDocumentFile(file);
      setLatestTask(result.task);
      setRows(await queryDocuments(filters));
      setGlobalNotice(`《${result.document.title}》已入库，索引任务已排队。`);
    } catch (error) {
      setGlobalNotice(error.message || "文档上传失败");
    } finally {
      setBusyAction("");
      event.target.value = "";
    }
  }

  async function handleReindex(document) {
    setBusyAction(`reindex:${document.id}`);
    setGlobalNotice(`《${document.title}》已加入后台索引队列。`);
    try {
      const result = await reindexDocument(document.id);
      setLatestTask(result.task);
      setRows(await queryDocuments(filters));
    } catch (error) {
      setGlobalNotice(error.message || "重建索引失败");
    } finally {
      setBusyAction("");
    }
  }

  async function handleDelete(document) {
    const confirmed = window.confirm(`确定要删除《${document.title}》吗？`);
    if (!confirmed) {
      return;
    }
    setBusyAction(`delete:${document.id}`);
    try {
      await deleteDocument(document.id);
      setRows(await queryDocuments(filters));
      setGlobalNotice(`《${document.title}》已从知识库删除。`);
    } catch (error) {
      setGlobalNotice(error.message || "文档删除失败");
    } finally {
      setBusyAction("");
    }
  }

  return (
    <div className="admin-content">
      <section className="dashboard-hero knowledge-hero">
        <div>
          <span className="hero-pill">知识库治理</span>
          <h2>知识库管理后台</h2>
          <p>按部门、标签、来源和状态筛选文档，查看后台索引进度，并识别哪些文档需要补齐向量或升级到当前向量版本。</p>
        </div>

        <div className="hero-actions">
          <label className="primary-action upload-button">
            上传文档
            <input type="file" accept=".txt,.md,.markdown,.pdf,.docx" onChange={handleUpload} hidden />
          </label>
        </div>
      </section>

      <section className="metric-grid knowledge-summary-grid">
        <article className="metric-card">
          <span>当前列表</span>
          <strong>{summary.total}</strong>
          <small>当前筛选条件下的文档数量。</small>
        </article>
        <article className="metric-card">
          <span>已索引</span>
          <strong>{summary.indexed}</strong>
          <small>检索链路可直接使用的文档。</small>
        </article>
        <article className="metric-card">
          <span>处理中</span>
          <strong>{summary.pending}</strong>
          <small>正在排队或后台处理中。</small>
        </article>
        <article className="metric-card">
          <span>向量过期</span>
          <strong>{summary.stale}</strong>
          <small>已索引但向量版本落后的文档。</small>
        </article>
        <article className="metric-card">
          <span>失败</span>
          <strong>{summary.failed}</strong>
          <small>需要排查的索引异常文档。</small>
        </article>
      </section>

      {latestTask ? (
        <section className="panel-card">
          <div className="panel-head">
            <div>
              <span className="panel-kicker">最近任务</span>
              <h3>{latestTask.kind_label}</h3>
            </div>
            <span
              className={`state-badge ${
                latestTask.status === "succeeded"
                  ? "indexed"
                  : latestTask.status === "failed"
                    ? "failed"
                    : "pending"
              }`}
            >
              {latestTask.status_label}
            </span>
          </div>
          <div className="definition-list compact">
            <div>
              <span>文档</span>
              <strong>{latestTask.document_title || "-"}</strong>
            </div>
            <div>
              <span>进度</span>
              <strong>{latestTask.progress}%</strong>
            </div>
            <div>
              <span>说明</span>
              <strong>{latestTask.message || "-"}</strong>
            </div>
            <div>
              <span>完成时间</span>
              <strong>{latestTask.completed_at ? formatDateTime(latestTask.completed_at) : "-"}</strong>
            </div>
          </div>
        </section>
      ) : null}

      <section className="panel-card">
        <div className="filter-bar filter-bar--knowledge">
          <input
            value={filters.q}
            onChange={(event) => updateFilter("q", event.target.value)}
            placeholder="按标题、内容、部门或标签搜索"
          />

          <select value={filters.department} onChange={(event) => updateFilter("department", event.target.value)}>
            <option value="">全部部门</option>
            {filterOptions.departments.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>

          <select value={filters.source_type} onChange={(event) => updateFilter("source_type", event.target.value)}>
            <option value="">全部来源</option>
            {filterOptions.sourceTypes.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>

          <select value={filters.index_state} onChange={(event) => updateFilter("index_state", event.target.value)}>
            <option value="">全部状态</option>
            <option value="pending">待索引</option>
            <option value="indexing">索引中</option>
            <option value="indexed">已索引</option>
            <option value="failed">索引失败</option>
          </select>

          <select value={filters.tag} onChange={(event) => updateFilter("tag", event.target.value)}>
            <option value="">全部标签</option>
            {filterOptions.tags.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>

          <select value={filters.sort_by} onChange={(event) => updateFilter("sort_by", event.target.value)}>
            <option value="updated_desc">最近更新优先</option>
            <option value="created_desc">最近创建优先</option>
            <option value="title_asc">标题 A-Z</option>
            <option value="title_desc">标题 Z-A</option>
          </select>
        </div>

        <div className="data-table">
          <div className="data-table-head data-table-head--knowledge">
            <span>文档</span>
            <span>来源</span>
            <span>状态</span>
            <span>最近任务</span>
            <span>操作</span>
          </div>

          {loading ? <div className="table-empty">正在加载知识库列表...</div> : null}

          {!loading && rows.length
            ? rows.map((document) => {
                const reindexBusy = busyAction === `reindex:${document.id}`;
                const deleteBusy = busyAction === `delete:${document.id}`;
                return (
                  <article key={document.id} className="data-row data-row--knowledge">
                    <div>
                      <strong>{document.title}</strong>
                      <small>{truncate(document.content_preview || "", 72)}</small>
                      <small>
                        {document.department} / {document.version} / {document.tag_count || 0} 个标签
                      </small>
                    </div>
                    <span>{sourceLabel(document)}</span>
                    <div className="detail-stack compact-gap">
                      <span
                        className={`state-badge ${
                          document.index_state === "indexed"
                            ? "indexed"
                            : document.index_state === "failed"
                              ? "failed"
                              : "pending"
                        }`}
                      >
                        {document.index_state_label}
                      </span>
                      <small>{document.indexed_label}</small>
                      <small>{document.embedding_label}</small>
                    </div>
                    <div className="detail-stack compact-gap">
                      <strong>{document.last_task?.kind_label || "暂无任务"}</strong>
                      <small>{document.last_task?.status_label || "尚未执行"}</small>
                      <small>{document.last_task?.updated_at ? formatDateTime(document.last_task.updated_at) : ""}</small>
                    </div>
                    <div className="inline-actions">
                      <button type="button" className="text-link" onClick={() => navigate(`/admin/knowledge/${document.id}`)}>
                        详情
                      </button>
                      <button
                        type="button"
                        className="text-link"
                        onClick={() => handleReindex(document)}
                        disabled={reindexBusy}
                      >
                        {reindexBusy ? "排队中..." : "重建索引"}
                      </button>
                      <button
                        type="button"
                        className="danger-text"
                        onClick={() => handleDelete(document)}
                        disabled={deleteBusy}
                      >
                        {deleteBusy ? "删除中..." : "删除"}
                      </button>
                    </div>
                  </article>
                );
              })
            : null}

          {!loading && !rows.length ? <div className="table-empty">当前筛选条件下没有匹配的文档。</div> : null}
        </div>
      </section>
    </div>
  );
}
