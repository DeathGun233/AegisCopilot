import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAppContext } from "../../context/AppContext";
import { truncate } from "../../lib/format";

function sourceLabel(document) {
  const mapping = {
    upload: "Uploaded file",
    seed: "Sample document",
    text: "Manual input",
    pdf: "PDF",
    docx: "Word",
    markdown: "Markdown",
  };
  return mapping[document.source_type] || document.source_type;
}

export function KnowledgePage() {
  const navigate = useNavigate();
  const { deleteDocument, documents, setGlobalNotice, uploadDocumentFile } = useAppContext();
  const [keyword, setKeyword] = useState("");
  const [busy, setBusy] = useState(false);

  const visibleDocuments = useMemo(() => {
    const needle = keyword.trim().toLowerCase();
    if (!needle) {
      return documents;
    }
    return documents.filter((document) =>
      [document.title, document.department, document.source_type, ...(document.tags || [])]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [documents, keyword]);

  async function handleUpload(event) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    setBusy(true);
    setGlobalNotice(`Importing ${file.name}...`);
    try {
      const result = await uploadDocumentFile(file);
      setGlobalNotice(`Imported ${result.document.title}. Added ${result.chunks_created} chunks.`);
    } catch (error) {
      setGlobalNotice(error.message || "Document upload failed.");
    } finally {
      setBusy(false);
      event.target.value = "";
    }
  }

  async function handleDelete(documentId) {
    try {
      await deleteDocument(documentId);
      setGlobalNotice("Document deleted from the knowledge base.");
    } catch (error) {
      setGlobalNotice(error.message || "Document deletion failed.");
    }
  }

  return (
    <div className="admin-content">
      <section className="dashboard-hero knowledge-hero">
        <div>
          <span className="hero-pill">Knowledge Base</span>
          <h2>Knowledge management</h2>
          <p>Upload documents, inspect indexing output, and open document detail pages for chunk-level review.</p>
        </div>

        <div className="hero-actions">
          <label className="primary-action upload-button">
            Upload document
            <input type="file" accept=".txt,.md,.markdown,.pdf,.docx" onChange={handleUpload} hidden disabled={busy} />
          </label>
        </div>
      </section>

      <section className="panel-card">
        <div className="filter-bar filter-bar--single">
          <input
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            placeholder="Search by title, department, source, or tag"
          />
        </div>

        <div className="data-table">
          <div className="data-table-head data-table-head--knowledge">
            <span>Document</span>
            <span>Department</span>
            <span>Source</span>
            <span>Status</span>
            <span>Actions</span>
          </div>

          {visibleDocuments.length ? (
            visibleDocuments.map((document) => (
              <article key={document.id} className="data-row data-row--knowledge">
                <div>
                  <strong>{document.title}</strong>
                  <small>{truncate(document.content_preview || "", 72)}</small>
                </div>
                <span>{document.department}</span>
                <span>{sourceLabel(document)}</span>
                <span className={document.indexed ? "state-badge indexed" : "state-badge pending"}>
                  {document.indexed ? `Indexed / ${document.chunk_count || 0} chunks` : "Pending"}
                </span>
                <div className="inline-actions">
                  <button type="button" className="text-link" onClick={() => navigate(`/admin/knowledge/${document.id}`)}>
                    Detail
                  </button>
                  <button type="button" className="danger-text" onClick={() => handleDelete(document.id)}>
                    Delete
                  </button>
                </div>
              </article>
            ))
          ) : (
            <div className="table-empty">No documents matched the current filter.</div>
          )}
        </div>
      </section>
    </div>
  );
}
