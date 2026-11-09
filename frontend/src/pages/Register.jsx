import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ErrorBox } from "../components/Layout/ui";
import { useAuth } from "../context/AuthContext";
import { api, errorMessage } from "../services/api";

export default function Register() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ full_name: "", email: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.register(form);
      await login(form.email, form.password);
      navigate("/");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <form onSubmit={submit} className="card w-full max-w-sm space-y-4 p-6">
        <div>
          <h1 className="text-xl font-semibold">Create account</h1>
          <p className="text-sm text-slate-500">New accounts get the Employee role.</p>
        </div>
        <ErrorBox message={error} />
        <div><label className="label" htmlFor="name">Full name</label>
          <input id="name" className="input" required maxLength={120} value={form.full_name} onChange={set("full_name")} /></div>
        <div><label className="label" htmlFor="email">Email</label>
          <input id="email" className="input" type="email" required value={form.email} onChange={set("email")} /></div>
        <div><label className="label" htmlFor="password">Password</label>
          <input id="password" className="input" type="password" required minLength={8} autoComplete="new-password" value={form.password} onChange={set("password")} />
          <p className="mt-1 text-xs text-slate-500">At least 8 characters with a letter and a digit.</p></div>
        <button className="btn-primary w-full" disabled={busy}>{busy ? "Creating..." : "Create account"}</button>
        <p className="text-center text-sm text-slate-500">Already registered? <Link className="text-brand-600 underline" to="/login">Sign in</Link></p>
      </form>
    </div>
  );
}
