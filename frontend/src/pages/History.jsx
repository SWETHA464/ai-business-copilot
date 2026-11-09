import { useState } from "react";
import { Link } from "react-router-dom";
import { Empty, ErrorBox, Notice, PageHeader, Spinner } from "../components/Layout/ui";
import { useAsync } from "../hooks/useAsync";
import { api, errorMessage } from "../services/api";
import { dateTime } from "../utils/format";

export default function History() {
  const { data, error, loading, reload } = useAsync(() => api.history());
  const [msg, setMsg] = useState("");
  const [filter, setFilter] = useState("");

  const remove = async (c) => {
    if (!window.confirm(`Delete conversation "${c.title}"? This cannot be undone.`)) return;
    try { await api.deleteConversation(c.id); setMsg(""); reload(); } catch (e) { setMsg(errorMessage(e)); }
  };
  const list = (data || []).filter((c) => c.title.toLowerCase().includes(filter.toLowerCase()));

  return (
    <div className="space-y-4">
      <PageHeader title="Conversation history" subtitle="Your past conversations. Only you can see them."
        actions={<Link className="btn-primary" to="/chat">New conversation</Link>} />
      <input className="input max-w-sm" placeholder="Filter by title" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter conversations" />
      {msg && <Notice tone="warn">{msg}</Notice>}
      {loading && <Spinner />}
      <ErrorBox message={error} onRetry={reload} />
      {!loading && !error && list.length === 0 && <Empty>{data?.length ? "No conversations match the filter." : "No conversations yet."}</Empty>}
      <ul className="space-y-2">
        {list.map((c) => (
          <li key={c.id} className="card flex items-center justify-between gap-3">
            <Link to={`/chat/${c.id}`} className="min-w-0">
              <div className="truncate font-medium hover:underline">{c.title}</div>
              <div className="text-xs text-slate-500">{c.message_count} message(s) - updated {dateTime(c.updated_at)}</div>
            </Link>
            <button className="btn-danger shrink-0" onClick={() => remove(c)}>Delete</button>
          </li>
        ))}
      </ul>
    </div>
  );
}
