import { useState } from "react";
import ReactMarkdown from "react-markdown";
import ChartRenderer from "../Charts/ChartRenderer";
import DataTable from "../Charts/DataTable";

function Collapsible({ title, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <button className="flex w-full items-center justify-between px-3 py-2 text-left text-xs font-semibold text-slate-600" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        {title}<span>{open ? "Hide" : "Show"}</span>
      </button>
      {open && <div className="border-t border-slate-100 p-3 text-xs">{children}</div>}
    </div>
  );
}

export function SqlPanel({ sql }) {
  if (!sql) return null;
  const failed = sql.status !== "ok";
  return (
    <Collapsible title={`SQL query ${failed ? "(not executed)" : `(${sql.row_count} rows, ${sql.elapsed_ms} ms, ${sql.source === "llm" ? "model-generated" : "template"})`}`}>
      {sql.query && <pre className="overflow-x-auto rounded bg-slate-900 p-3 text-slate-100">{sql.query}</pre>}
      {sql.params && Object.keys(sql.params).length > 0 && (
        <p className="mt-2 text-slate-500">Parameters: <code>{JSON.stringify(sql.params)}</code></p>
      )}
      {failed && <p className="mt-2 text-amber-700">{sql.message || "The query could not be executed safely."}</p>}
      {!failed && sql.rows?.length > 0 && (
        <div className="mt-3"><DataTable columns={sql.columns} rows={sql.rows} maxHeight="14rem" /></div>
      )}
      {sql.truncated && <p className="mt-2 text-slate-500">Result truncated for display.</p>}
    </Collapsible>
  );
}

export function Citations({ citations }) {
  if (!citations?.length) return null;
  return (
    <Collapsible title={`Sources (${citations.length})`} defaultOpen>
      <ol className="space-y-2">
        {citations.map((c) => (
          <li key={c.id} className="rounded border border-slate-100 bg-slate-50 p-2">
            <div className="font-semibold text-slate-700">[{c.id}] {c.filename}{c.page ? `, page ${c.page}` : ""} <span className="font-normal text-slate-400">({c.category})</span></div>
            <div className="mt-1 text-slate-600">{c.snippet}</div>
          </li>
        ))}
      </ol>
    </Collapsible>
  );
}

function External({ external }) {
  if (!external) return null;
  return (
    <Collapsible title={`External research (${external.status})`} defaultOpen={external.results?.length > 0}>
      {external.message && <p className="mb-2 text-slate-600">{external.message}</p>}
      <ul className="space-y-2">
        {(external.results || []).map((r) => (
          <li key={r.url}>
            <a className="font-medium text-brand-600 underline" href={r.url} target="_blank" rel="noopener noreferrer">{r.title}</a>
            <div className="text-slate-500">{r.snippet}</div>
          </li>
        ))}
      </ul>
    </Collapsible>
  );
}

function Details({ meta }) {
  const checks = meta.verification?.checks || [];
  return (
    <Collapsible title="How this answer was produced">
      {meta.route && <p className="mb-2">Tools used: <b>{meta.route.tools?.join(", ") || "none"}</b>{meta.route.reason ? ` (${meta.route.reason})` : ""}</p>}
      {checks.length > 0 && (
        <ul className="mb-2 space-y-0.5">
          {checks.map((c, i) => <li key={i}>{c.ok ? "✔" : "✖"} {c.check}{c.detail ? ` - ${c.detail}` : ""}</li>)}
        </ul>
      )}
      {meta.steps?.length > 0 && (
        <ul className="text-slate-500">{meta.steps.map((s, i) => <li key={i}>{s.node}: {s.ms} ms{s.detail ? ` - ${s.detail}` : ""}</li>)}</ul>
      )}
      <p className="mt-2 text-slate-500">Wording by {meta.llm_used ? "the language model (figures checked against calculations)" : "deterministic templates (no model used)"}.</p>
    </Collapsible>
  );
}

export default function MessageBubble({ message }) {
  const isUser = message.role === "user";
  const meta = message.meta || {};
  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-brand-600 px-4 py-2.5 text-sm text-white">{message.content}</div>
      </div>
    );
  }
  return (
    <div className="flex justify-start">
      <div className="w-full max-w-[95%] space-y-3">
        <div className={`rounded-2xl rounded-bl-sm border px-4 py-3 text-sm ${meta.error ? "border-red-200 bg-red-50 text-red-700" : "border-slate-200 bg-white"}`}>
          <div className="prose-chat"><ReactMarkdown>{message.content}</ReactMarkdown></div>
        </div>
        {(meta.needs_approval || []).map((a, i) => (
          <div key={i} className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">{a.message}</div>
        ))}
        {(meta.warnings || []).length > 0 && (
          <ul className="space-y-1 text-xs text-amber-700">{meta.warnings.map((w, i) => <li key={i}>⚠ {w}</li>)}</ul>
        )}
        {(meta.charts || []).map((c, i) => <ChartRenderer key={i} spec={c} />)}
        {(meta.tables || []).slice(0, 2).map((t, i) => <DataTable key={i} title={t.title} columns={t.columns} rows={t.rows} />)}
        <SqlPanel sql={meta.sql} />
        <Citations citations={meta.citations} />
        <External external={meta.external} />
        {(meta.route || meta.verification) && <Details meta={meta} />}
      </div>
    </div>
  );
}
