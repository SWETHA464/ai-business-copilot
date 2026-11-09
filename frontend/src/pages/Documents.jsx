import { useRef, useState } from "react";
import { ErrorBox, Empty, Notice, PageHeader, Spinner } from "../components/Layout/ui";
import { useAsync } from "../hooks/useAsync";
import { useAuth } from "../context/AuthContext";
import { api, errorMessage } from "../services/api";
import { bytes, dateTime } from "../utils/format";

const STATUS_STYLE = {
  ready: "bg-emerald-100 text-emerald-700",
  processing: "bg-amber-100 text-amber-700",
  failed: "bg-red-100 text-red-700",
};

export default function Documents() {
  const { user } = useAuth();
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [department, setDepartment] = useState("");
  const params = { ...(q && { q }), ...(category && { category }), ...(department && { department }) };
  const docs = useAsync(() => api.documents(params), [q, category, department]);
  const filters = useAsync(() => api.documentFilters());

  const [upload, setUpload] = useState({ category: "general", department: "general", visibility: "shared" });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState({ tone: "", text: "" });
  const fileRef = useRef(null);

  const [sq, setSq] = useState("");
  const [search, setSearch] = useState(null);
  const [searching, setSearching] = useState(false);
  const [detail, setDetail] = useState(null);

  const doUpload = async (e) => {
    e.preventDefault();
    const f = fileRef.current?.files?.[0];
    if (!f) { setMsg({ tone: "warn", text: "Choose a PDF, DOCX, TXT or CSV file first." }); return; }
    const form = new FormData();
    form.append("file", f);
    Object.entries(upload).forEach(([k, v]) => form.append(k, v));
    setBusy(true); setMsg({ tone: "", text: "" });
    try {
      const d = await api.uploadDocument(form);
      setMsg({ tone: d.status === "ready" ? "ok" : "warn", text: `Uploaded "${d.filename}" - status: ${d.status}${d.error ? ` (${d.error})` : ""}.` });
      fileRef.current.value = "";
      docs.reload(); filters.reload();
    } catch (err) {
      setMsg({ tone: "warn", text: errorMessage(err) });
    } finally { setBusy(false); }
  };

  const act = async (fn, okText) => {
    try { await fn(); if (okText) setMsg({ tone: "ok", text: okText }); docs.reload(); }
    catch (err) { setMsg({ tone: "warn", text: errorMessage(err) }); }
  };

  const remove = (d) => {
    if (!window.confirm(`Delete "${d.filename}"? It will no longer be searchable.`)) return;
    act(() => api.deleteDocument(d.id), `Deleted "${d.filename}".`);
  };

  const doSearch = async (e) => {
    e.preventDefault();
    if (sq.trim().length < 2) return;
    setSearching(true); setSearch(null);
    try { setSearch(await api.searchDocuments({ query: sq.trim(), category: category || null, department: department || null })); }
    catch (err) { setMsg({ tone: "warn", text: errorMessage(err) }); }
    finally { setSearching(false); }
  };

  const view = async (d) => {
    try { setDetail(await api.document(d.id)); } catch (err) { setMsg({ tone: "warn", text: errorMessage(err) }); }
  };

  const list = docs.data || [];
  return (
    <div className="space-y-5">
      <PageHeader title="Documents" subtitle="Upload business documents so the assistant can cite them. Supported: PDF, DOCX, TXT, CSV."
        actions={user.role === "admin" && (
          <button className="btn-secondary" onClick={() => act(() => api.rebuildIndex(), "Search index rebuilt from stored chunks.")}>Rebuild index</button>
        )} />
      {msg.text && <Notice tone={msg.tone || "info"}>{msg.text}</Notice>}

      <form className="card grid gap-3 md:grid-cols-5" onSubmit={doUpload}>
        <div className="md:col-span-2"><label className="label" htmlFor="file">File</label>
          <input id="file" ref={fileRef} type="file" accept=".pdf,.docx,.txt,.csv" className="input" /></div>
        <div><label className="label" htmlFor="cat">Category</label>
          <input id="cat" className="input" value={upload.category} onChange={(e) => setUpload({ ...upload, category: e.target.value })} maxLength={100} /></div>
        <div><label className="label" htmlFor="dep">Department</label>
          <input id="dep" className="input" value={upload.department} onChange={(e) => setUpload({ ...upload, department: e.target.value })} maxLength={100} /></div>
        <div><label className="label" htmlFor="vis">Visibility</label>
          <select id="vis" className="input" value={upload.visibility} onChange={(e) => setUpload({ ...upload, visibility: e.target.value })}>
            <option value="shared">Shared with everyone</option><option value="private">Private (only me)</option></select></div>
        <div className="md:col-span-5"><button className="btn-primary" disabled={busy}>{busy ? "Uploading and indexing..." : "Upload"}</button></div>
      </form>

      <form className="card flex flex-wrap gap-2" onSubmit={doSearch}>
        <input className="input min-w-0 flex-1" placeholder="Search inside your documents (e.g. refund window)" value={sq} onChange={(e) => setSq(e.target.value)} aria-label="Search document contents" />
        <button className="btn-primary" disabled={searching}>{searching ? "Searching..." : "Search content"}</button>
      </form>
      {search && (
        <div className="card space-y-3">
          <h2 className="text-sm font-semibold text-slate-700">Search results for "{search.query}"</h2>
          {!search.sufficient_evidence && <Notice tone="warn">No strongly matching passages were found; the results below may not be relevant.</Notice>}
          {search.hits.length === 0 && <p className="text-sm text-slate-500">No matching passages.</p>}
          {search.hits.map((h, i) => (
            <div key={i} className="rounded-lg border border-slate-200 p-3 text-sm">
              <div className="mb-1 font-medium">{h.filename}{h.page ? ` - page ${h.page}` : ""} <span className="badge bg-slate-100 text-slate-600">{h.category}</span></div>
              <p className="text-slate-600">{h.snippet}</p>
            </div>
          ))}
        </div>
      )}

      <div className="card flex flex-wrap items-end gap-3">
        <div className="min-w-[12rem] flex-1"><label className="label" htmlFor="q">Filter by name</label>
          <input id="q" className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="File name contains..." /></div>
        <div><label className="label" htmlFor="fc">Category</label>
          <select id="fc" className="input" value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">All</option>{(filters.data?.categories || []).map((c) => <option key={c}>{c}</option>)}</select></div>
        <div><label className="label" htmlFor="fd">Department</label>
          <select id="fd" className="input" value={department} onChange={(e) => setDepartment(e.target.value)}>
            <option value="">All</option>{(filters.data?.departments || []).map((c) => <option key={c}>{c}</option>)}</select></div>
      </div>

      {docs.loading && <Spinner />}
      <ErrorBox message={docs.error} onRetry={docs.reload} />
      {!docs.loading && !docs.error && list.length === 0 && <Empty>No documents match. Upload one above, or run <code>python scripts/index_documents.py</code> to load the samples.</Empty>}
      {list.length > 0 && (
        <div className="card overflow-x-auto p-0">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>{["Name", "Type", "Category", "Department", "Access", "Uploaded", "Status", "Actions"].map((h) => <th key={h} className="px-3 py-2">{h}</th>)}</tr>
            </thead>
            <tbody>
              {list.map((d) => (
                <tr key={d.id} className="border-t border-slate-100">
                  <td className="px-3 py-2"><div className="font-medium">{d.filename}</div><div className="text-xs text-slate-400">{bytes(d.size_bytes)} - {d.page_count} page(s) - {d.chunk_count} chunks</div></td>
                  <td className="px-3 py-2 uppercase">{d.file_type}</td>
                  <td className="px-3 py-2">{d.category}</td>
                  <td className="px-3 py-2">{d.department}</td>
                  <td className="px-3 py-2 capitalize">{d.visibility}</td>
                  <td className="whitespace-nowrap px-3 py-2">{dateTime(d.created_at)}</td>
                  <td className="px-3 py-2"><span className={`badge ${STATUS_STYLE[d.status] || "bg-slate-100 text-slate-600"}`} title={d.error || ""}>{d.status}</span></td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <button className="mr-2 text-brand-600 hover:underline" onClick={() => view(d)}>View</button>
                    {d.can_modify && <>
                      <button className="mr-2 text-brand-600 hover:underline" onClick={() => act(() => api.reindexDocument(d.id), `Re-indexed "${d.filename}".`)}>Reindex</button>
                      <button className="text-red-600 hover:underline" onClick={() => remove(d)}>Delete</button>
                    </>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {detail && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" onClick={() => setDetail(null)}>
          <div className="max-h-[85vh] w-full max-w-2xl overflow-auto rounded-xl bg-white p-5" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-lg font-semibold">{detail.filename}</h2>
            <p className="mb-3 text-xs text-slate-500">{detail.file_type.toUpperCase()} - {bytes(detail.size_bytes)} - {detail.category} / {detail.department} - {detail.status}</p>
            <h3 className="label">Preview</h3>
            <pre className="whitespace-pre-wrap rounded bg-slate-50 p-3 text-xs text-slate-700">{detail.preview || "No preview available."}</pre>
            <button className="btn-secondary mt-4" onClick={() => setDetail(null)}>Close</button>
          </div>
        </div>
      )}
    </div>
  );
}
