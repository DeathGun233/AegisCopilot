import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useAppContext } from "../../context/AppContext";
import { formatDateTime, truncate } from "../../lib/format";

function sourceLabel(document) {
  const mapping = {
    upload: "Uploaded file",
    seed: "Sample document",
    text: "Manual input",
    pdf: "PDF",
    docx: "Word",
    markdown: "Markdown",
  };
  return mapping[document?.source_type] || document?.source_type || "-";
}

export function DocumentDetailPage() {
  const { documentId } = useParams();
  const navigate = useNavigate();
  const { deleteDocument, fetchDocument, setGlobalNotice } = useAppContext();
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

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
          setError(loadError.message || "Failed to load the document.");
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

  async function handleDelete() {
    try {
      await deleteDocument(documentId);
      setGlobalNotice("Document deleted from the knowledge base.");
      navigate("/admin/knowledge", { replace: true });
    } catch (deleteError) {
      setGlobalNotice(deleteError.message || "Document deletion failed.");
    }
  }

  return (
    <div className="admin-content">
      <section className="dashboard-hero">
        <div>
          <span className="hero-pill">Document Detail</span>
          <h2>{detail?.document?.title || "Loading document"}</h2>
          <p>Inspect the stored source content and the chunk breakdown that powers retrieval.</p>
        </div>

        <div className="hero-actions">
          <Link className="secondary-action" to="/admin/knowledge">
            Back to list
          </Link>
          <button type="button" className="danger-outline" onClick={handleDelete} disabled={!detail}>
            Delete document
          </button>
        </div>
      </section>

      {loading ? <section className="panel-card table-empty">Loading document detail...</section> : null}
      {error ? <section className="panel-card table-empty">{error}</section> : null}

      {detail ? (
        <section className="admin-grid two-columns">
          <article className="panel-card">
            <div className="panel-head">
              <div>
                <span className="panel-kicker">Metadata</span>
                <h3>Document profile</h3>
              </div>
            </div>

            <div className="definition-list">
              <div>
                <span>Department</span>
                <strong>{detail.document.department}</strong>
              </div>
              <div>
                <span>Source</span>
                <strong>{sourceLabel(detail.document)}</strong>
              </div>
              <div>
                <span>Status</span>
                <strong>{detail.document.indexed ? "Indexed" : "Pending"}</strong>
              </div>
              <div>
                <span>Indexed at</span>
                <strong>{detail.document.indexed_at ? formatDateTime(detail.document.indexed_at) : "-"}</strong>
              </div>
              <div>
                <span>Version</span>
                <strong>{detail.document.version}</strong>
              </div>
              <div>
                <span>Tags</span>
                <strong>{detail.document.tags?.join(", ") || "-"}</strong>
              </div>
            </div>

            <div className="detail-block">
              <span>Source content preview</span>
              <p>{truncate(detail.document.content || "", 800)}</p>
            </div>
          </article>

          <article className="panel-card">
            <div className="panel-head">
              <div>
                <span className="panel-kicker">Chunks</span>
                <h3>Chunk breakdown</h3>
              </div>
            </div>

            <div className="chunk-list">
              {detail.chunks.length ? (
                detail.chunks.map((chunk) => (
                  <article key={chunk.id} className="chunk-card">
                    <strong>Chunk {chunk.chunk_index + 1}</strong>
                    <small>{chunk.token_count} tokens</small>
                    <p>{chunk.text_preview}</p>
                  </article>
                ))
              ) : (
                <div className="table-empty">This document has not been indexed yet.</div>
              )}
            </div>
          </article>
        </section>
      ) : null}
    </div>
  );
}
