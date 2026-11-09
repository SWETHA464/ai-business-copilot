import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import MessageBubble from "../components/Chat/MessageBubble";
import { ErrorBox, Notice, Spinner } from "../components/Layout/ui";
import { useStoredState } from "../hooks/useAsync";
import { api, errorMessage } from "../services/api";

const EXAMPLES = [
  "Which five products generated the highest revenue last quarter?",
  "What is our refund policy?",
  "Why did sales decrease, and what do our internal reports say?",
  "Compare Q2 and Q3 revenue by product.",
];

export default function Chat() {
  const { conversationId } = useParams();
  const navigate = useNavigate();
  const [conversations, setConversations] = useState([]);
  const [messages, setMessages] = useState([]);
  const [convId, setConvId] = useState(conversationId ? Number(conversationId) : null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [loadingConv, setLoadingConv] = useState(false);
  const [error, setError] = useState("");
  const [allowExternal, setAllowExternal] = useStoredState("copilot_allow_external", false);
  const bottom = useRef(null);

  const refreshList = useCallback(() => api.history().then(setConversations).catch(() => {}), []);
  useEffect(() => { refreshList(); }, [refreshList]);

  // Load the selected conversation (or reset for a new one) whenever the route changes.
  useEffect(() => {
    setError("");
    if (!conversationId) { setConvId(null); setMessages([]); return; }
    // Skip reloading when we just created this conversation locally.
    if (Number(conversationId) === convId && messages.length > 0) return;
    setLoadingConv(true);
    api.conversation(conversationId)
      .then((c) => { setConvId(c.id); setMessages(c.messages); })
      .catch((e) => { setError(errorMessage(e)); setMessages([]); })
      .finally(() => setLoadingConv(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, sending]);

  const send = async (text) => {
    const q = (text ?? input).trim();
    if (!q || sending) return;
    setInput("");
    setError("");
    setSending(true);
    setMessages((m) => [...m, { id: `tmp-${Date.now()}`, role: "user", content: q }]);
    try {
      const res = await api.chat({ message: q, conversation_id: convId, allow_external: allowExternal });
      setMessages((m) => [...m, res.message]);
      if (!convId) {
        setConvId(res.conversation_id);
        navigate(`/chat/${res.conversation_id}`, { replace: true });
      }
      refreshList();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSending(false);
    }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this conversation?")) return;
    try {
      await api.deleteConversation(id);
      if (id === convId) navigate("/chat");
      refreshList();
    } catch (e) { setError(errorMessage(e)); }
  };

  return (
    <div className="flex h-[calc(100vh-3rem)] gap-4">
      <aside className="hidden w-64 shrink-0 flex-col rounded-xl border border-slate-200 bg-white lg:flex">
        <div className="p-3"><Link className="btn-primary w-full" to="/chat">+ New conversation</Link></div>
        <ul className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-2">
          {conversations.length === 0 && <li className="px-2 py-3 text-xs text-slate-400">No conversations yet.</li>}
          {conversations.map((c) => (
            <li key={c.id} className={`group flex items-center rounded-lg ${c.id === convId ? "bg-brand-50" : "hover:bg-slate-100"}`}>
              <Link to={`/chat/${c.id}`} className="min-w-0 flex-1 truncate px-2 py-2 text-sm">{c.title}</Link>
              <button className="px-2 text-xs text-slate-400 hover:text-red-600" aria-label={`Delete ${c.title}`} onClick={() => remove(c.id)}>✕</button>
            </li>
          ))}
        </ul>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col rounded-xl border border-slate-200 bg-slate-50">
        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          {loadingConv && <Spinner label="Loading conversation" />}
          {!loadingConv && messages.length === 0 && (
            <div className="mx-auto mt-10 max-w-xl text-center">
              <h1 className="text-lg font-semibold">Ask about your business</h1>
              <p className="mt-1 text-sm text-slate-500">Questions can use sales data, internal documents, or both.</p>
              <div className="mt-4 grid gap-2">
                {EXAMPLES.map((e) => <button key={e} className="btn-secondary justify-start text-left" onClick={() => send(e)}>{e}</button>)}
              </div>
            </div>
          )}
          {messages.map((m) => <MessageBubble key={m.id} message={m} />)}
          {sending && <Spinner label="Analyzing data and documents..." />}
          <div ref={bottom} />
        </div>
        <div className="space-y-2 border-t border-slate-200 bg-white p-3">
          <ErrorBox message={error} />
          {allowExternal && <Notice tone="warn">External web research is on: a short search query derived from your question will be sent to the search provider.</Notice>}
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); send(); }}>
            <textarea className="input min-h-[2.75rem] flex-1 resize-none" rows={2} maxLength={2000} placeholder="Ask a question..." value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
            <button className="btn-primary self-end" disabled={sending || !input.trim()}>Send</button>
          </form>
          <label className="flex items-center gap-2 text-xs text-slate-500">
            <input type="checkbox" checked={allowExternal} onChange={(e) => setAllowExternal(e.target.checked)} />
            Allow external web research for questions about industry trends
          </label>
        </div>
      </section>
    </div>
  );
}
