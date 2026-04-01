import { useEffect, useMemo, useState } from "react";
import { useAppContext } from "../../context/AppContext";
import { formatDateTime, truncate } from "../../lib/format";

const emptyFilters = {
  q: "",
  intent: "",
  grounded: "",
  limit: 30,
};

function formatTraceValue(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  if (Array.isArray(value)) {
    if (!value.length) {
      return "-";
    }
    if (value.every((item) => typeof item !== "object" || item === null)) {
      return value.join(" / ");
    }
    return JSON.stringify(value, null, 2);
  }
  if (typeof value === "object") {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
}

function TraceValue({ value }) {
  const rendered = formatTraceValue(value);
  const multiline = typeof rendered === "string" && (rendered.includes("\n") || rendered.length > 120);
  if (multiline) {
    return <pre className="trace-pre">{rendered}</pre>;
  }
  return <strong>{rendered}</strong>;
}

function groundedBadge(grounded) {
  return grounded ? "indexed" : "pending";
}

export function TracePage() {
  const { fetchAgentTask, fetchAgentTasks, setGlobalNotice } = useAppContext();
  const [filters, setFilters] = useState(emptyFilters);
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function loadTasks() {
      setLoading(true);
      try {
        const data = await fetchAgentTasks({
          q: filters.q,
          intent: filters.intent,
          grounded: filters.grounded === "" ? null : filters.grounded,
          limit: filters.limit,
        });
        if (cancelled) {
          return;
        }
        setRows(data);
        setSelectedTaskId((current) => {
          if (current && data.some((item) => item.id === current)) {
            return current;
          }
          return data[0]?.id || "";
        });
      } catch (error) {
        if (!cancelled) {
          setGlobalNotice(error.message || "任务观测列表加载失败");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    loadTasks();
    return () => {
      cancelled = true;
    };
  }, [fetchAgentTasks, filters, setGlobalNotice]);

  useEffect(() => {
    let cancelled = false;
    if (!selectedTaskId) {
      setDetail(null);
      return () => {
        cancelled = true;
      };
    }

    async function loadDetail() {
      setDetailLoading(true);
      try {
        const data = await fetchAgentTask(selectedTaskId);
        if (!cancelled) {
          setDetail(data);
        }
      } catch (error) {
        if (!cancelled) {
          setGlobalNotice(error.message || "任务详情加载失败");
        }
      } finally {
        if (!cancelled) {
          setDetailLoading(false);
        }
      }
    }

    loadDetail();
    return () => {
      cancelled = true;
    };
  }, [fetchAgentTask, selectedTaskId, setGlobalNotice]);

  const selectedSummary = detail?.summary || null;
  const traceItems = detail?.task?.trace || [];

  const summaryMetrics = useMemo(() => {
    const total = rows.length;
    const grounded = rows.filter((item) => item.grounded).length;
    const pending = rows.filter((item) => !item.grounded).length;
    const taskIntent = rows.filter((item) => item.intent === "task").length;
    return { total, grounded, pending, taskIntent };
  }, [rows]);

  function updateFilter(key, value) {
    setFilters((current) => ({ ...current, [key]: value }));
  }

  return (
    <div className="admin-content">
      <section className="dashboard-hero">
        <div>
          <span className="hero-pill">任务观测</span>
          <h2>链路观测与排障中心</h2>
          <p>查看每次问答如何被改写、路由、检索和依据校验，快速排查误答、漏召回和澄清问题。</p>
        </div>
      </section>

      <section className="metric-grid">
        <article className="metric-card">
          <span>当前任务</span>
          <strong>{summaryMetrics.total}</strong>
          <small>当前筛选条件下的任务数量。</small>
        </article>
        <article className="metric-card">
          <span>已通过依据校验</span>
          <strong>{summaryMetrics.grounded}</strong>
          <small>证据充分、通过依据校验的任务。</small>
        </article>
        <article className="metric-card">
          <span>待排查</span>
          <strong>{summaryMetrics.pending}</strong>
          <small>证据不足或需要继续排查的任务。</small>
        </article>
        <article className="metric-card">
          <span>任务整理</span>
          <strong>{summaryMetrics.taskIntent}</strong>
          <small>被识别为总结、梳理、对比类的任务数。</small>
        </article>
      </section>

      <section className="panel-card">
        <div className="filter-bar">
          <input
            value={filters.q}
            onChange={(event) => updateFilter("q", event.target.value)}
            placeholder="按问题、答案、路由原因或引用文档搜索"
          />
          <select value={filters.intent} onChange={(event) => updateFilter("intent", event.target.value)}>
            <option value="">全部意图</option>
            <option value="knowledge_qa">知识问答</option>
            <option value="task">任务整理</option>
            <option value="chitchat">寒暄闲聊</option>
          </select>
          <select value={filters.grounded} onChange={(event) => updateFilter("grounded", event.target.value)}>
            <option value="">全部依据状态</option>
            <option value="true">已通过依据校验</option>
            <option value="false">待排查</option>
          </select>
        </div>
      </section>

      <section className="admin-grid trace-layout">
        <article className="panel-card">
          <div className="panel-head">
            <div>
              <span className="panel-kicker">任务列表</span>
              <h3>最近问答任务</h3>
            </div>
            <small>{loading ? "加载中..." : `${rows.length} 条`}</small>
          </div>

          <div className="data-table">
            {loading ? <div className="table-empty">正在加载任务列表...</div> : null}

            {!loading && rows.length
              ? rows.map((item) => (
                  <article
                    key={item.id}
                    className={selectedTaskId === item.id ? "data-row active trace-row" : "data-row trace-row"}
                    onClick={() => setSelectedTaskId(item.id)}
                  >
                    <div className="detail-stack compact-gap">
                      <strong>{truncate(item.query, 44)}</strong>
                      <small>{truncate(item.route_reason || "暂无路由说明", 64)}</small>
                      <small>
                        {item.intent_label} · 引用 {item.citations_count} · 步骤 {item.trace_steps}
                      </small>
                    </div>
                    <div className="detail-stack compact-gap">
                      <span className={`state-badge ${groundedBadge(item.grounded)}`}>
                        {item.grounded ? "已通过依据校验" : "待排查"}
                      </span>
                      <small>最高分 {item.top_score}</small>
                      <small>{formatDateTime(item.created_at)}</small>
                    </div>
                  </article>
                ))
              : null}

            {!loading && !rows.length ? <div className="table-empty">当前筛选条件下还没有任务。</div> : null}
          </div>
        </article>

        <article className="panel-card">
          <div className="panel-head">
            <div>
              <span className="panel-kicker">任务详情</span>
              <h3>{selectedSummary ? truncate(selectedSummary.query, 32) : "选择一条任务查看详情"}</h3>
            </div>
            <small>{detailLoading ? "正在加载..." : selectedSummary ? formatDateTime(selectedSummary.created_at) : ""}</small>
          </div>

          {!selectedTaskId ? <div className="table-empty">左侧暂无可查看的任务。</div> : null}
          {selectedTaskId && detailLoading ? <div className="table-empty">正在加载任务详情...</div> : null}

          {selectedSummary && !detailLoading ? (
            <div className="detail-stack">
              <div className="definition-list">
                <div>
                  <span>意图</span>
                  <strong>{selectedSummary.intent_label}</strong>
                </div>
                <div>
                  <span>依据校验</span>
                  <strong>{selectedSummary.grounded ? "已通过" : "未通过"}</strong>
                </div>
                <div>
                  <span>最高分</span>
                  <strong>{selectedSummary.top_score}</strong>
                </div>
                <div>
                  <span>引用数量</span>
                  <strong>{selectedSummary.citations_count}</strong>
                </div>
              </div>

              <div className="detail-block">
                <span>路由原因</span>
                <strong>{selectedSummary.route_reason || "-"}</strong>
              </div>

              <div className="detail-block">
                <span>最终回答</span>
                <p>{detail.task.final_answer || "-"}</p>
              </div>

              <div className="detail-block">
                <span>引用证据</span>
                <div className="chunk-list">
                  {detail.task.citations?.length ? (
                    detail.task.citations.map((item) => (
                      <article key={item.chunk_id} className="chunk-card">
                        <strong>{item.display_source || item.source}</strong>
                        <p>{truncate(item.text, 180)}</p>
                        <small>
                          总分 {item.score} / 关键词 {item.keyword_score} / 语义 {item.semantic_score} / 重排{" "}
                          {item.rerank_score}
                        </small>
                        <small>
                          命中查询 {item.matched_query || "-"} / 变体 {item.query_variant}
                        </small>
                      </article>
                    ))
                  ) : (
                    <div className="table-empty">这条任务没有引用证据。</div>
                  )}
                </div>
              </div>

              <div className="detail-block">
                <span>链路过程</span>
                <div className="trace-step-list">
                  {traceItems.map((item, index) => (
                    <article key={`${item.step}-${index}`} className="trace-step-card">
                      <strong>{item.step}</strong>
                      <div className="definition-list compact">
                        {Object.entries(item)
                          .filter(([key]) => key !== "step")
                          .map(([key, value]) => (
                            <div key={key}>
                              <span>{key}</span>
                              <TraceValue value={value} />
                            </div>
                          ))}
                      </div>
                    </article>
                  ))}
                </div>
              </div>
            </div>
          ) : null}
        </article>
      </section>
    </div>
  );
}
