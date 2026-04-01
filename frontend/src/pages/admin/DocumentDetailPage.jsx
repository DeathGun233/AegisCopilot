import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useAppContext } from "../../context/AppContext";
import { formatDateTime, truncate } from "../../lib/format";

function sourceLabel(document) {
  return document?.source_label?.split(" / ")[0] || document?.source_type || "-";
}

function isTaskActive(task) {
  return task && (task.status === "pending" || task.status === "running");
}

export function DocumentDetailPage() {
  const { documentId } = useParams();
  const navigate = useNavigate();
  const { deleteDocument, fetchDocument, fetchUploadTask, reindexDocument, setGlobalNotice } = useAppContext();
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyAction, setBusyAction] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function loadDetail() {
      setLoading(true);
      setError("");
      try {
        const data = await fetchDocument(documentId);
        if (!cancelled) {
          setDetail(data);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError.message || "文档加载失败");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    loadDetail();
    return () => {
      cancelled = true;
    };
  }, [documentId, fetchDocument]);

  useEffect(() => {
    const latestTask = detail?.recent_tasks?.[0];
    if (!latestTask || !isTaskActive(latestTask)) {
      return undefined;
    }

    const timer = window.setInterval(async () => {
      try {
        const [taskResponse, documentResponse] = await Promise.all([
          fetchUploadTask(latestTask.id),
          fetchDocument(documentId),
        ]);
        setDetail(documentResponse);
        if (!isTaskActive(taskResponse.task)) {
          const title = documentResponse.document?.title || latestTask.document_title || "当前文档";
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
  }, [detail, documentId, fetchDocument, fetchUploadTask, setGlobalNotice]);

  async function reloadDetail() {
    const data = await fetchDocument(documentId);
    setDetail(data);
    return data;
  }

  async function handleDelete() {
    const confirmed = window.confirm(`确定要删除《${detail?.document?.title || "当前文档"}》吗？`);
    if (!confirmed) {
      return;
    }
    setBusyAction("delete");
    try {
      await deleteDocument(documentId);
      setGlobalNotice("文档已从知识库删除。");
      navigate("/admin/knowledge", { replace: true });
    } catch (deleteError) {
      setGlobalNotice(deleteError.message || "文档删除失败");
    } finally {
      setBusyAction("");
    }
  }

  async function handleReindex() {
    if (!detail?.document) {
      return;
    }
    setBusyAction("reindex");
    try {
      await reindexDocument(documentId);
      await reloadDetail();
      setGlobalNotice(`《${detail.document.title}》已加入后台索引队列。`);
    } catch (reindexError) {
      setGlobalNotice(reindexError.message || "重建索引失败");
    } finally {
      setBusyAction("");
    }
  }

  const document = detail?.document;

  return (
    <div className="admin-content">
      <section className="dashboard-hero">
        <div>
          <span className="hero-pill">文档详情</span>
          <h2>{document?.title || "正在加载文档"}</h2>
          <p>查看文档元信息、向量版本、后台索引任务和片段拆分结果，便于治理、排查和升级重建。</p>
        </div>

        <div className="hero-actions">
          <Link className="secondary-action" to="/admin/knowledge">
            返回列表
          </Link>
          <button type="button" className="secondary-action" onClick={handleReindex} disabled={!detail || busyAction === "reindex"}>
            {busyAction === "reindex" ? "排队中..." : "重建索引"}
          </button>
          <button type="button" className="danger-outline" onClick={handleDelete} disabled={!detail || busyAction === "delete"}>
            {busyAction === "delete" ? "删除中..." : "删除文档"}
          </button>
        </div>
      </section>

      {loading ? <section className="panel-card table-empty">正在加载文档详情...</section> : null}
      {error ? <section className="panel-card table-empty">{error}</section> : null}

      {detail ? (
        <>
          <section className="metric-grid knowledge-summary-grid">
            <article className="metric-card">
              <span>索引状态</span>
              <strong>{document.index_state_label}</strong>
              <small>{document.indexed_label}</small>
            </article>
            <article className="metric-card">
              <span>片段数量</span>
              <strong>{document.chunk_count}</strong>
              <small>当前文档已写入的 chunk 数量。</small>
            </article>
            <article className="metric-card">
              <span>向量状态</span>
              <strong>{document.embedding_stale ? "版本过期" : document.embedding_ready ? "已就绪" : "待补建"}</strong>
              <small>{document.embedding_label}</small>
            </article>
            <article className="metric-card">
              <span>最后更新</span>
              <strong>{formatDateTime(document.updated_at) || "-"}</strong>
              <small>文档治理信息的最近更新时间。</small>
            </article>
          </section>

          <section className="admin-grid two-columns">
            <article className="panel-card">
              <div className="panel-head">
                <div>
                  <span className="panel-kicker">元数据</span>
                  <h3>文档信息</h3>
                </div>
              </div>

              <div className="definition-list">
                <div>
                  <span>部门</span>
                  <strong>{document.department}</strong>
                </div>
                <div>
                  <span>来源</span>
                  <strong>{sourceLabel(document)}</strong>
                </div>
                <div>
                  <span>版本</span>
                  <strong>{document.version}</strong>
                </div>
                <div>
                  <span>创建时间</span>
                  <strong>{formatDateTime(document.created_at) || "-"}</strong>
                </div>
                <div>
                  <span>索引时间</span>
                  <strong>{document.indexed_at ? formatDateTime(document.indexed_at) : "-"}</strong>
                </div>
                <div>
                  <span>向量版本</span>
                  <strong>{document.embedding_version || "未记录"}</strong>
                </div>
                <div>
                  <span>当前版本</span>
                  <strong>{document.current_embedding_version || "-"}</strong>
                </div>
                <div>
                  <span>最近错误</span>
                  <strong>{document.last_index_error || "-"}</strong>
                </div>
              </div>

              <div className="detail-block">
                <span>标签</span>
                <p>{document.tags?.length ? document.tags.join("、") : "暂无标签"}</p>
              </div>

              <div className="detail-block">
                <span>原始内容预览</span>
                <p>{truncate(document.content || "", 1200)}</p>
              </div>
            </article>

            <article className="panel-card">
              <div className="panel-head">
                <div>
                  <span className="panel-kicker">治理任务</span>
                  <h3>最近任务记录</h3>
                </div>
              </div>

              <div className="chunk-list">
                {detail.recent_tasks.length ? (
                  detail.recent_tasks.map((task) => (
                    <article key={task.id} className="chunk-card">
                      <strong>
                        {task.kind_label} / {task.status_label}
                      </strong>
                      <p>
                        进度 {task.progress}% / {task.message || "暂无说明"}
                      </p>
                      <small>
                        更新时间 {formatDateTime(task.updated_at) || "-"}
                        {task.chunks_created ? ` / 片段 ${task.chunks_created}` : ""}
                      </small>
                      {task.error ? <small>错误信息：{task.error}</small> : null}
                    </article>
                  ))
                ) : (
                  <div className="table-empty">当前文档还没有治理任务记录。</div>
                )}
              </div>
            </article>
          </section>

          <section className="panel-card">
            <div className="panel-head">
              <div>
                <span className="panel-kicker">片段拆分</span>
                <h3>片段明细</h3>
              </div>
              <small>{detail.chunks.length} 个片段</small>
            </div>

            <div className="chunk-list">
              {detail.chunks.length ? (
                detail.chunks.map((chunk) => (
                  <article key={chunk.id} className="chunk-card">
                    <strong>片段 {chunk.chunk_index + 1}</strong>
                    <small>{chunk.token_count} 个词元</small>
                    <p>{chunk.text_preview}</p>
                    <small>
                      {chunk.metadata?.department || "-"} / {chunk.metadata?.version || "-"}
                    </small>
                  </article>
                ))
              ) : (
                <div className="table-empty">当前文档还没有可用索引片段。</div>
              )}
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
