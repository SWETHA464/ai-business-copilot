import { Link } from "react-router-dom";
import ChartRenderer from "../components/Charts/ChartRenderer";
import { ObjectTable } from "../components/Charts/DataTable";
import KpiCard from "../components/Dashboard/KpiCard";
import { ErrorBox, Notice, PageHeader, Spinner } from "../components/Layout/ui";
import { useAsync } from "../hooks/useAsync";
import { api } from "../services/api";
import { dateTime, money, money2, num, pct } from "../utils/format";

const ACTIVITY_LINK = { conversation: (a) => `/chat/${a.id}`, report: () => "/reports", document: () => "/documents" };

export default function Dashboard() {
  const { data, error, loading, reload } = useAsync(() => api.dashboard());
  if (loading) return <Spinner />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  const k = data.kpis;

  return (
    <div className="space-y-5">
      <PageHeader title="Dashboard" subtitle={k ? `Figures cover completed orders only. Data through ${k.reference_date}.` : undefined} />
      {data.empty ? <Notice tone="warn">{data.message}</Notice> : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <KpiCard label="Total revenue" value={money(k.total_revenue)} hint="Completed orders" />
            <KpiCard label="Total orders" value={num(k.total_orders)} hint={`${num(k.completed_orders)} completed`} />
            <KpiCard label="Total customers" value={num(k.total_customers)} hint={`${num(k.active_customers)} have purchased`} />
            <KpiCard label="Average order value" value={money2(k.average_order_value)} hint={`Cancellation rate ${pct(k.cancellation_rate_pct)}`} />
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <ChartRenderer spec={{ type: "line", title: "Monthly revenue", xKey: "month", series: [{ key: "revenue", label: "Revenue" }], data: data.monthly_revenue, valueFormat: "currency" }} />
            </div>
            <ObjectTable title="Top-selling products (by revenue)" rows={data.top_products} columns={["rank", "product", "revenue", "units"]} />
          </div>
        </>
      )}
      <div className="card">
        <h2 className="mb-2 text-sm font-semibold text-slate-700">Recent activity</h2>
        {data.recent_activity.length === 0 ? (
          <p className="text-sm text-slate-500">Nothing yet. <Link className="text-brand-600 underline" to="/chat">Ask the assistant a question</Link>.</p>
        ) : (
          <ul className="divide-y divide-slate-100 text-sm">
            {data.recent_activity.map((a, i) => (
              <li key={i} className="flex items-center justify-between gap-3 py-2">
                <Link className="min-w-0 truncate hover:underline" to={ACTIVITY_LINK[a.type](a)}>
                  <span className="badge mr-2 bg-slate-100 capitalize text-slate-600">{a.type}</span>{a.title}
                </Link>
                <span className="shrink-0 text-xs text-slate-400">{dateTime(a.at)}</span>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-xs text-slate-400">{num(data.documents_indexed)} document(s) indexed for search.</p>
      </div>
    </div>
  );
}
