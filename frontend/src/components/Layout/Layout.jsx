import { useState } from "react";
import { NavLink, Navigate, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { Spinner } from "./ui";

const NAV = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/chat", label: "AI Assistant" },
  { to: "/documents", label: "Documents" },
  { to: "/analytics", label: "Analytics" },
  { to: "/history", label: "Conversations" },
  { to: "/reports", label: "Reports" },
  { to: "/settings", label: "Settings" },
];

export function ProtectedRoute() {
  const { user, loading } = useAuth();
  if (loading) return <div className="p-10"><Spinner label="Checking session" /></div>;
  if (!user) return <Navigate to="/login" replace />;
  return <Layout />;
}

function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);

  const link = ({ isActive }) =>
    `block rounded-lg px-3 py-2 text-sm font-medium ${isActive ? "bg-brand-600 text-white" : "text-slate-300 hover:bg-white/10"}`;

  return (
    <div className="flex min-h-screen">
      <aside className={`${open ? "block" : "hidden"} fixed inset-y-0 left-0 z-30 w-60 shrink-0 bg-brand-900 p-4 md:static md:block`}>
        <div className="mb-6 px-2 text-base font-semibold text-white">AI Business Copilot</div>
        <nav className="space-y-1" onClick={() => setOpen(false)}>
          {NAV.map((n) => <NavLink key={n.to} to={n.to} end={n.end} className={link}>{n.label}</NavLink>)}
        </nav>
        <div className="absolute inset-x-4 bottom-4 border-t border-white/10 pt-3 text-xs text-slate-300">
          <div className="truncate font-medium text-white">{user.full_name}</div>
          <div className="truncate">{user.email}</div>
          <div className="mb-2 capitalize">{user.role}</div>
          <button className="rounded-md bg-white/10 px-3 py-1.5 text-white hover:bg-white/20" onClick={() => { logout(); navigate("/login"); }}>
            Sign out
          </button>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-slate-200 bg-white px-4 py-3 md:hidden">
          <button className="btn-secondary" aria-label="Toggle navigation" onClick={() => setOpen((o) => !o)}>Menu</button>
          <span className="font-semibold">AI Business Copilot</span>
        </header>
        <main className="min-w-0 flex-1 p-4 md:p-6"><Outlet /></main>
      </div>
    </div>
  );
}
