import { ErrorBox, Notice, PageHeader, Spinner } from "../components/Layout/ui";
import { useStoredState, useAsync } from "../hooks/useAsync";
import { useAuth } from "../context/AuthContext";
import { api } from "../services/api";
import { num } from "../utils/format";

const Row = ({ k, v }) => (
  <div className="flex justify-between gap-4 border-b border-slate-100 py-1.5 text-sm last:border-0">
    <span className="text-slate-500">{k}</span><span className="text-right font-medium">{String(v)}</span>
  </div>
);

export default function Settings() {
  const { user } = useAuth();
  const { data, error, loading, reload } = useAsync(() => api.status());
  const [allowExternal, setAllowExternal] = useStoredState("copilot_allow_external", false);

  return (
    <div className="space-y-4">
      <PageHeader title="Settings and system status" subtitle="Your profile, preferences and the state of the application's components." />
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card">
          <h2 className="mb-2 text-sm font-semibold">Profile</h2>
          <Row k="Name" v={user.full_name} /><Row k="Email" v={user.email} /><Row k="Role" v={user.role} />
        </div>
        <div className="card">
          <h2 className="mb-2 text-sm font-semibold">Preferences</h2>
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-1" checked={allowExternal} onChange={(e) => setAllowExternal(e.target.checked)} />
            <span>Allow external web research in chat by default<br /><span className="text-xs text-slate-500">Stored in this browser only. Requires a Tavily API key on the server.</span></span>
          </label>
        </div>
      </div>
      {loading && <Spinner />}
      <ErrorBox message={error} onRetry={reload} />
      {data && (
        <>
          {data.warnings.length > 0 && <Notice tone="warn"><ul className="list-disc pl-5">{data.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></Notice>}
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="card"><h2 className="mb-2 text-sm font-semibold">Application</h2>
              <Row k="Version" v={data.app.version} /><Row k="Environment" v={data.app.environment} />
              <Row k="Database" v={data.database.dialect} /><Row k="Read-only SQL connection" v={data.database.readonly_connection} />
              {Object.entries(data.database.business_rows).map(([t, n]) => <Row key={t} k={`${t} rows`} v={num(n)} />)}</div>
            <div className="card"><h2 className="mb-2 text-sm font-semibold">Language model</h2>
              {Object.entries(data.llm).map(([k, v]) => <Row key={k} k={k} v={v} />)}</div>
            <div className="card"><h2 className="mb-2 text-sm font-semibold">Retrieval (RAG)</h2>
              {Object.entries(data.rag).filter(([, v]) => typeof v !== "object").map(([k, v]) => <Row key={k} k={k} v={v} />)}
              {data.rag.index && <Row k="index consistent" v={data.rag.index.consistent ?? JSON.stringify(data.rag.index)} />}</div>
            <div className="card"><h2 className="mb-2 text-sm font-semibold">Integrations and limits</h2>
              <Row k="External research" v={data.integrations.external_research.detail} />
              <Row k="LangSmith tracing" v={data.integrations.langsmith.enabled ? "enabled" : "off (optional)"} />
              <Row k="Max upload" v={`${data.limits.max_upload_mb} MB`} /><Row k="SQL max rows" v={data.limits.sql_max_rows} /><Row k="SQL timeout" v={`${data.limits.sql_timeout_seconds}s`} /></div>
          </div>
        </>
      )}
    </div>
  );
}
