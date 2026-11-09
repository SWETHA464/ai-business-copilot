import axios from "axios";

const TOKEN_KEY = "copilot_token";

export const tokenStore = {
  get: () => { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } },
  set: (t) => { try { localStorage.setItem(TOKEN_KEY, t); } catch { /* storage unavailable */ } },
  clear: () => { try { localStorage.removeItem(TOKEN_KEY); } catch { /* storage unavailable */ } },
};

const http = axios.create({ baseURL: import.meta.env.VITE_API_URL || "", timeout: 180000 });

http.interceptors.request.use((cfg) => {
  const t = tokenStore.get();
  if (t) cfg.headers.Authorization = `Bearer ${t}`;
  return cfg;
});

let onUnauthorized = () => {};
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };

http.interceptors.response.use(
  (r) => r,
  (err) => {
    const url = err.config?.url || "";
    if (err.response?.status === 401 && !url.includes("/auth/login")) onUnauthorized();
    return Promise.reject(err);
  },
);

/** Turn any axios/FastAPI error into a readable message. */
export function errorMessage(err) {
  if (!err) return "Unknown error";
  if (err.code === "ECONNABORTED") return "The request timed out. The model may be slow; try again.";
  if (!err.response) return "Cannot reach the backend. Is it running on port 8000?";
  const d = err.response.data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x.msg || "Invalid input").join("; ");
  if (err.response.status === 429) return "Too many requests. Please wait a moment.";
  return `Request failed (${err.response.status})`;
}

export const api = {
  // auth
  register: (b) => http.post("/api/auth/register", b).then((r) => r.data),
  login: (b) => http.post("/api/auth/login", b).then((r) => r.data),
  me: () => http.get("/api/auth/me").then((r) => r.data),
  // chat
  chat: (b) => http.post("/api/chat", b).then((r) => r.data),
  history: () => http.get("/api/chat/history").then((r) => r.data),
  conversation: (id) => http.get(`/api/chat/${id}`).then((r) => r.data),
  deleteConversation: (id) => http.delete(`/api/chat/${id}`),
  // documents
  documents: (params) => http.get("/api/documents", { params }).then((r) => r.data),
  documentFilters: () => http.get("/api/documents/filters").then((r) => r.data),
  document: (id) => http.get(`/api/documents/${id}`).then((r) => r.data),
  uploadDocument: (form) => http.post("/api/documents/upload", form).then((r) => r.data),
  reindexDocument: (id) => http.post(`/api/documents/${id}/reindex`).then((r) => r.data),
  deleteDocument: (id) => http.delete(`/api/documents/${id}`),
  searchDocuments: (b) => http.post("/api/documents/search", b).then((r) => r.data),
  rebuildIndex: () => http.post("/api/documents/rebuild-index").then((r) => r.data),
  // analytics
  dashboard: () => http.get("/api/dashboard/summary").then((r) => r.data),
  revenue: () => http.get("/api/analytics/revenue").then((r) => r.data),
  products: (quarter) => http.get("/api/analytics/products", { params: quarter ? { quarter } : {} }).then((r) => r.data),
  customers: () => http.get("/api/analytics/customers").then((r) => r.data),
  analyticsQuery: (question) => http.post("/api/analytics/query", { question }).then((r) => r.data),
  // reports
  reports: () => http.get("/api/reports").then((r) => r.data),
  report: (id) => http.get(`/api/reports/${id}`).then((r) => r.data),
  generateReport: (b) => http.post("/api/reports/generate", b).then((r) => r.data),
  downloadReport: async (id, title) => {
    const r = await http.get(`/api/reports/${id}/download`, { responseType: "blob" });
    const url = URL.createObjectURL(r.data);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(title || "report").replace(/[^A-Za-z0-9_-]+/g, "_").slice(0, 60)}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
  // system
  health: () => http.get("/api/health").then((r) => r.data),
  status: () => http.get("/api/status").then((r) => r.data),
};
