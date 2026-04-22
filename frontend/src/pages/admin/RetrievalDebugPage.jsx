import { useEffect, useMemo, useState } from "react";
import { useAppContext } from "../../context/AppContext";
import { truncate } from "../../lib/format";

const defaultQuery = "员工请假审批流程";

const baseConfig = {
  top_k: 3,
  candidate_k: 8,
  keyword_weight: 0.55,
  semantic_weight: 0.45,
  rerank_weight: 0.6,
  min_score: 0.08,
};

const compareConfig = {
  top_k: 5,
  candidate_k: 16,
  keyword_weight: 0.35,
  semantic_weight: 0.65,
  rerank_weight: 0.8,
  min_score: 0.04,
};

const filterLabels = {
  selected: "已选中",
  outside_top_k: "超出 top-k",
  duplicate: "重复片段",
  below_min_score: "低于阈值",
  outside_candidate_k: "超出候选池",
  candidate: "候选",
};

function numberValue(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function toPayload(query, config) {
  return {
    query,
    top_k: numberValue(config.top_k),
    candidate_k: numberValue(config.candidate_k),
    keyword_weight: numberValue(config.keyword_weight),
    semantic_weight: numberValue(config.semantic_weight),
    rerank_weight: numberValue(config.rerank_weight),
    min_score: numberValue(config.min_score),
  };
}

function summarizeFilters(candidates = []) {
  return candidates.reduce((summary, item) => {
    const key = item.filter_reason || "candidate";
    return { ...summary, [key]: (summary[key] || 0) + 1 };
  }, {});
}

function ConfigFields({ config, onChange }) {
  return (
    <div className="definition-list">
      <label className="toolbar-field">
        <span>top-k</span>
        <input
          type="number"
          min="1"
          max="10"
          value={config.top_k}
          onChange={(event) => onChange("top_k", event.target.value)}
        />
      </label>
      <label className="toolbar-field">
        <span>candidate-k</span>
        <input
          type="number"
          min="1"
          max="40"
          value={config.candidate_k}
          onChange={(event) => onChange("candidate_k", event.target.value)}
        />
      </label>
      <label className="toolbar-field">
        <span>关键词权重</span>
        <input
          type="number"
          min="0"
          step="0.05"
          value={config.keyword_weight}
          onChange={(event) => onChange("keyword_weight", event.target.value)}
        />
      </label>
      <label className="toolbar-field">
        <span>语义权重</span>
        <input
          type="number"
          min="0"
          step="0.05"
          value={config.semantic_weight}
          onChange={(event) => onChange("semantic_weight", event.target.value)}
        />
      </label>
      <label className="toolbar-field">
        <span>重排强度</span>
        <input
          type="number"
          min="0"
          step="0.05"
          value={config.rerank_weight}
          onChange={(event) => onChange("rerank_weight", event.target.value)}
        />
      </label>
      <label className="toolbar-field">
        <span>最小分数</span>
        <input
          type="number"
          min="0"
          max="1"
          step="0.01"
          value={config.min_score}
          onChange={(event) => onChange("min_score", event.target.value)}
        />
      </label>
    </div>
  );
}

function DebugColumn({ title, debug }) {
  const filterSummary = useMemo(() => summarizeFilters(debug?.candidates), [debug]);

  return (
    <article className="panel-card retrieval-debug-column">
      <div className="panel-head">
        <div>
          <span className="panel-kicker">试跑方案</span>
          <h3>{title}</h3>
        </div>
        <span className="status-pill live">{debug?.results?.length || 0} 条</span>
      </div>

      {debug ? (
        <div className="detail-stack">
          <div className="definition-list compact">
            <div>
              <span>改写 query</span>
              <strong>{debug.understanding?.rewritten_query || debug.query || "-"}</strong>
            </div>
            <div>
              <span>query variants</span>
              <strong>{debug.query_variants?.map((item) => `${item.label}:${item.query}`).join(" / ") || "-"}</strong>
            </div>
          </div>

          <div className="debug-filter-row">
            {Object.entries(filterLabels).map(([key, label]) => (
              <span key={key} className={`debug-filter-pill ${key}`}>
                {label} {filterSummary[key] || 0}
              </span>
            ))}
          </div>

          <div className="chunk-list">
            {debug.results?.length ? (
              debug.results.map((item) => (
                <article key={`${title}-${item.chunk_id}-${item.query_variant}`} className="chunk-card">
                  <strong>
                    #{item.rank} {item.display_source || item.source}
                  </strong>
                  <p>{truncate(item.text, 150)}</p>
                  <small>
                    总分 {item.score} / 关键词 {item.keyword_score} / 语义 {item.semantic_score} / 重排{" "}
                    {item.rerank_score}
                  </small>
                  <small>
                    {item.semantic_source} / {item.query_variant} / {item.matched_query || "-"}
                  </small>
                </article>
              ))
            ) : (
              <div className="table-empty">暂无命中结果。</div>
            )}
          </div>

          <div className="debug-candidate-table">
            <div className="debug-candidate-head">
              <span>片段</span>
              <span>状态</span>
              <span>分数</span>
            </div>
            {(debug.candidates || []).slice(0, 12).map((item, index) => (
              <div key={`${title}-${item.chunk_id}-${item.query_variant}-${index}`} className="debug-candidate-row">
                <span>{item.display_source || item.source}</span>
                <span>{filterLabels[item.filter_reason] || item.filter_reason}</span>
                <span>
                  {item.score} / {item.keyword_score} / {item.semantic_score}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="table-empty">等待试跑。</div>
      )}
    </article>
  );
}

export function RetrievalDebugPage() {
  const { debugRetrieval, fetchRetrievalSettings, setGlobalNotice } = useAppContext();
  const [query, setQuery] = useState(defaultQuery);
  const [leftConfig, setLeftConfig] = useState(baseConfig);
  const [rightConfig, setRightConfig] = useState(compareConfig);
  const [leftDebug, setLeftDebug] = useState(null);
  const [rightDebug, setRightDebug] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchRetrievalSettings()
      .then((settings) => {
        if (cancelled) {
          return;
        }
        setLeftConfig({
          top_k: settings.top_k,
          candidate_k: settings.candidate_k,
          keyword_weight: settings.keyword_weight,
          semantic_weight: settings.semantic_weight,
          rerank_weight: settings.rerank_weight,
          min_score: settings.min_score,
        });
      })
      .catch((error) => setGlobalNotice(error.message || "检索参数加载失败"));
    return () => {
      cancelled = true;
    };
  }, [fetchRetrievalSettings, setGlobalNotice]);

  function updateConfig(side, key, value) {
    const setter = side === "left" ? setLeftConfig : setRightConfig;
    setter((current) => ({ ...current, [key]: value }));
  }

  async function handleRun(event) {
    event.preventDefault();
    setLoading(true);
    try {
      const [left, right] = await Promise.all([
        debugRetrieval(toPayload(query, leftConfig)),
        debugRetrieval(toPayload(query, rightConfig)),
      ]);
      setLeftDebug(left);
      setRightDebug(right);
      setGlobalNotice("检索调试已完成");
    } catch (error) {
      setGlobalNotice(error.message || "检索调试失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="admin-content">
      <section className="dashboard-hero">
        <div>
          <span className="hero-pill">Retrieval Debug</span>
          <h2>检索调试</h2>
        </div>
      </section>

      <form className="panel-card detail-stack" onSubmit={handleRun}>
        <label className="toolbar-field">
          <span>测试问题</span>
          <textarea
            className="dashboard-preview-textarea"
            rows={3}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <section className="retrieval-config-grid">
          <div className="detail-stack">
            <div className="panel-head">
              <h3>方案 A</h3>
            </div>
            <ConfigFields config={leftConfig} onChange={(key, value) => updateConfig("left", key, value)} />
          </div>
          <div className="detail-stack">
            <div className="panel-head">
              <h3>方案 B</h3>
            </div>
            <ConfigFields config={rightConfig} onChange={(key, value) => updateConfig("right", key, value)} />
          </div>
        </section>
        <div className="inline-actions">
          <button type="submit" className="primary-action" disabled={loading}>
            {loading ? "试跑中..." : "执行对比"}
          </button>
        </div>
      </form>

      <section className="retrieval-debug-grid">
        <DebugColumn title="方案 A" debug={leftDebug} />
        <DebugColumn title="方案 B" debug={rightDebug} />
      </section>
    </div>
  );
}
