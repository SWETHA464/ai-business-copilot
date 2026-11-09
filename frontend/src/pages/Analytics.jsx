import { useState } from "react";
import ChartRenderer from "../components/Charts/ChartRenderer";
import DataTable, { ObjectTable } from "../components/Charts/DataTable";
import { ErrorBox, Notice, PageHeader, Spinner } from "../components/Layout/ui";
import { useAsync } from "../hooks/useAsync";
import { api, errorMessage } from "../services/api";
import { money, pct } from "../utils/format";

const TABS = ["Revenue", "Products", "Customers", "Ask analytics"];

function Definitions({ defs }) {
  if (!defs) return null;
  return (
    <details className="card text-sm text-slate-600">
      <summary className="cursor-pointer font-medium text-slate-700">How these metrics are defined</summary>
      <ul className="mt-2 list-disc space-y-1 pl-5">{Object.entries(defs).map(([k, v]) => <li key={k}><b className="capitalize">{k}:</b> {typeof v === "string" ? v : JSON.stringify(v)}</li>)}</ul>
    </details>
  );
}

function Revenue() {
  const { data, error, loading, reload } = useAsync(() => api.revenue());
  if (loading) return <Spinner />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (data.empty) return <Notice tone="warn">{data.message}</Notice>;
  const c = data.comparison;
  return (
    <div className="space-y-4">
      {c?.current_quarter && (
        <div className="card text-sm">
          <b>{c.current_quarter}</b> revenue {money(c.current_revenue)} vs <b>{c.previous_quarter}</b> {money(c.previous_revenue)}
          {c.change_pct != null && <> - <span className={c.change_pct < 0 ? "font-semibold text-red-600" : "font-semibold text-emerald-600"}>{pct(c.change_pct)}</span></>}
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-2">{data.charts.map((s) => <ChartRenderer key={s.title} spec={s} />)}</div>
      <Definitions defs={data.definitions} />
    </div>
  );
}

function Products() {
  const [quarter, setQuarter] = useState("");
  const { data, error, loading, reload } = useAsync(() => api.products(quarter), [quarter]);
  if (loading && !data) return <Spinner />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (data.empty) return <Notice tone="warn">{data.message}</Notice>;
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2"><label className="label mb-0" htmlFor="qsel">Quarter</label>
        <select id="qsel" className="input w-40" value={quarter} onChange={(e) => setQuarter(e.target.value)}>
          <option value="">All time</option>{data.available_quarters.map((q) => <option key={q}>{q}</option>)}</select></div>
      {data.charts.map((s) => <ChartRenderer key={s.title} spec={s} />)}
      <ObjectTable title="Product performance" rows={data.products} />
      {data.comparison?.products?.length > 0 && <ObjectTable title={`Change: ${data.comparison.previous_quarter} to ${data.comparison.current_quarter}`} rows={data.comparison.products} />}
      <Definitions defs={data.definitions} />
    </div>
  );
}

function Customers() {
  const { data, error, loading, reload } = useAsync(() => api.customers());
  if (loading) return <Spinner />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (data.empty) return <Notice tone="warn">{data.message}</Notice>;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-3">{data.charts.map((s) => <ChartRenderer key={s.title} spec={s} />)}</div>
      <div className="grid gap-4 lg:grid-cols-2">
        <ObjectTable title="Customer segments" rows={data.segments} />
        <ObjectTable title="Payment status" rows={data.payment_status} />
      </div>
      <Definitions defs={data.definitions} />
    </div>
  );
}

function AskAnalytics() {
  const [question, setQuestion] = useState("");
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError(""); setRes(null);
    try { setRes(await api.analyticsQuery(question)); } catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  };
  return (
    <div className="space-y-4">
      <form className="card flex flex-wrap gap-2" onSubmit={submit}>
        <input className="input min-w-0 flex-1" value={question} onChange={(e) => setQuestion(e.target.value)} minLength={3} maxLength={500}
          placeholder="e.g. Compare Q2 and Q3 revenue by product" aria-label="Analytics question" />
        <button className="btn-primary" disabled={busy || question.trim().length < 3}>{busy ? "Calculating..." : "Run"}</button>
      </form>
      <p className="text-xs text-slate-500">All numbers are calculated from the database with pandas; no language model is used for the figures.</p>
      <ErrorBox message={error} />
      {res?.empty && <Notice tone="warn">{res.message}</Notice>}
      {res && !res.empty && (
        <div className="space-y-4">
          {res.bullets?.length > 0 && <div className="card"><ul className="list-disc space-y-1 pl-5 text-sm">{res.bullets.map((b, i) => <li key={i}>{b}</li>)}</ul></div>}
          {(res.charts || []).map((s) => <ChartRenderer key={s.title} spec={s} />)}
          {(res.tables || []).map((t, i) => <DataTable key={i} title={t.title} columns={t.columns} rows={t.rows} />)}
          <Definitions defs={res.definitions && Object.fromEntries((Array.isArray(res.definitions) ? res.definitions : []).map((d, i) => [`note ${i + 1}`, d]))} />
        </div>
      )}
    </div>
  );
}

export default function Analytics() {
  const [tab, setTab] = useState(TABS[0]);
  return (
    <div className="space-y-4">
      <PageHeader title="Business analytics" subtitle="Interactive charts calculated from completed orders." />
      <div className="flex flex-wrap gap-1 border-b border-slate-200" role="tablist">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${tab === t ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-800"}`}>{t}</button>
        ))}
      </div>
      {tab === "Revenue" && <Revenue />}
      {tab === "Products" && <Products />}
      {tab === "Customers" && <Customers />}
      {tab === "Ask analytics" && <AskAnalytics />}
    </div>
  );
}
