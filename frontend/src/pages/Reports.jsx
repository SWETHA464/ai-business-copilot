import { useState } from "react";
import ChartRenderer from "../components/Charts/ChartRenderer";
import DataTable from "../components/Charts/DataTable";
import { Empty, ErrorBox, Notice, PageHeader, Spinner } from "../components/Layout/ui";
import { useAsync } from "../hooks/useAsync";
import { api, errorMessage } from "../services/api";
import { dateTime } from "../utils/format";

function Section({ title, label, children }) {
  return (
    <section className="card space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold text-slate-800">{title}</h3>
        {label && <span className="badge bg-slate-100 text-slate-600">{label}</span>}
      </div>
      {children}
    </section>
  );
}

function ReportView({ report, onDownload }) {
  const c = report.content;
  const ev = c.document_evidence;
  const ext = c.external_research;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">{c.title}</h2>
        {report.has_pdf && <button className="btn-primary" onClick={onDownload}>Download PDF</button>}
      </div>
      <Section title="Executive summary"><p className="whitespace-pre-wrap text-sm">{c.executive_summary}</p></Section>
      <Section title="Business question"><p className="text-sm">{c.business_question}</p></Section>
      <Section title="Key findings" label={c.key_findings.label}>
        {c.key_findings.items.length ? <ul className="list-disc pl-5 text-sm">{c.key_findings.items.map((b, i) => <li key={i}>{b}</li>)}</ul> : <p className="text-sm text-slate-500">No calculated findings.</p>}
      </Section>
      {c.metrics.rows?.length > 0 && <Section title="Relevant metrics" label={c.metrics.label}><DataTable columns={["Metric", "Value"]} rows={c.metrics.rows} /></Section>}
      {(c.analysis.tables || []).length > 0 && <Section title="Analysis" label={c.analysis.label}>
        {c.analysis.tables.map((t, i) => <DataTable key={i} title={t.title} columns={t.columns} rows={t.rows} />)}
      </Section>}
      {(c.charts || []).length > 0 && <div className="grid gap-4 lg:grid-cols-2">{c.charts.map((s) => <ChartRenderer key={s.title} spec={s} />)}</div>}
      <Section title="Supporting documents" label={ev.label}>
        {ev.answer ? <p className="whitespace-pre-wrap text-sm">{ev.answer}</p> : <p className="text-sm text-slate-500">No document evidence was used.</p>}
        {(ev.citations || []).length > 0 && <ul className="list-disc pl-5 text-xs text-slate-600">{ev.citations.map((x, i) => <li key={i}>{x.filename}{x.page ? `, page ${x.page}` : ""}</li>)}</ul>}
      </Section>
      <Section title="External research" label={ext.label}>
        {!ext.requested && <p className="text-sm text-slate-500">Not requested.</p>}
        {ext.approval_note && <Notice tone="warn">{ext.approval_note}</Notice>}
        {ext.data?.status && ext.data.status !== "ok" && <p className="text-sm text-slate-500">{ext.data.message || ext.data.status}</p>}
        {ext.data?.results?.length > 0 && <ul className="list-disc pl-5 text-sm">{ext.data.results.map((s, i) => <li key={i}><a className="text-brand-600 underline" href={s.url} target="_blank" rel="noopener noreferrer">{s.title || s.url}</a></li>)}</ul>}
      </Section>
      <Section title="Conclusions"><ul className="list-disc pl-5 text-sm">{(c.conclusions || []).map((b, i) => <li key={i}>{typeof b === "string" ? b : JSON.stringify(b)}</li>)}</ul></Section>
      <Section title="Recommendations" label={c.recommendations.label}>
        {c.recommendations.items?.length ? <ul className="list-disc pl-5 text-sm">{c.recommendations.items.map((b, i) => <li key={i}>{b}</li>)}</ul> : <p className="text-sm text-slate-500">{c.recommendations.note || "None."}</p>}
      </Section>
      {(c.warnings || []).length > 0 && <Notice tone="warn">{c.warnings.join(" ")}</Notice>}
    </div>
  );
}

export default function Reports() {
  const list = useAsync(() => api.reports());
  const [question, setQuestion] = useState("");
  const [allowExternal, setAllowExternal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [current, setCurrent] = useState(null);

  const generate = async (e) => {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      const r = await api.generateReport({ question: question.trim(), allow_external: allowExternal });
      setCurrent(r); setQuestion(""); list.reload();
    } catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  };
  const open = async (id) => {
    setError("");
    try { setCurrent(await api.report(id)); } catch (err) { setError(errorMessage(err)); }
  };
  const download = async (r) => { try { await api.downloadReport(r.id, r.title); } catch (err) { setError(errorMessage(err)); } };

  return (
    <div className="space-y-4">
      <PageHeader title="Reports" subtitle="Generate a business report with verified numbers, document evidence and clearly labelled AI recommendations." />
      <form className="card space-y-3" onSubmit={generate}>
        <label className="label" htmlFor="rq">Business question</label>
        <textarea id="rq" className="input" rows={2} minLength={5} maxLength={1000} value={question} onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. Revenue declined last quarter. Which products were affected and what do our reports say?" />
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={allowExternal} onChange={(e) => setAllowExternal(e.target.checked)} /> Allow external web research (requires a Tavily key)</label>
        <button className="btn-primary" disabled={busy || question.trim().length < 5}>{busy ? "Generating (this can take a minute)..." : "Generate report"}</button>
      </form>
      <ErrorBox message={error} />
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-2">
          <h2 className="text-sm font-semibold text-slate-700">Your reports</h2>
          {list.loading && <Spinner />}
          <ErrorBox message={list.error} onRetry={list.reload} />
          {!list.loading && !list.error && !(list.data || []).length && <Empty>No reports yet.</Empty>}
          {(list.data || []).map((r) => (
            <div key={r.id} className={`card cursor-pointer p-3 text-sm ${current?.id === r.id ? "ring-2 ring-brand-500" : ""}`}>
              <button className="block w-full text-left font-medium hover:underline" onClick={() => open(r.id)}>{r.title}</button>
              <div className="mt-1 flex items-center justify-between text-xs text-slate-500">
                <span>{dateTime(r.created_at)}</span>
                {r.has_pdf && <button className="text-brand-600 hover:underline" onClick={() => download(r)}>PDF</button>}
              </div>
            </div>
          ))}
        </div>
        <div className="lg:col-span-2">
          {current ? <ReportView report={current} onDownload={() => download(current)} /> : <Empty>Select or generate a report to view it.</Empty>}
        </div>
      </div>
    </div>
  );
}
