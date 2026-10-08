import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, auth, describeError } from "../api";
import { ErrorBanner } from "../components/ui";

export default function Login() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [form, setForm] = useState({ organization_name: "", name: "", email: "", password: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = mode === "login" ? { email: form.email, password: form.password } : form;
      const { access_token, role } = await api.post<{ access_token: string; role?: string }>(`/auth/${mode}`, body);
      auth.set(access_token, role ?? "owner");
      navigate(role === "customer" ? "/portal" : mode === "register" ? "/settings" : "/");
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  return (
    <div className="auth-page">
      <form className="card auth-card" onSubmit={submit}>
        <div className="brand large">
          Growth<span>OS</span>
        </div>
        <p className="muted">An AI operating system for business growth and customer relationships. Business owners and customers sign in here.</p>
        <ErrorBanner error={error} />
        {mode === "register" && (
          <>
            <label>
              Company / organization name
              <input required value={form.organization_name} onChange={set("organization_name")} />
            </label>
            <label>
              Your name
              <input value={form.name} onChange={set("name")} />
            </label>
          </>
        )}
        <label>
          Email
          <input type="email" required value={form.email} onChange={set("email")} />
        </label>
        <label>
          Password
          <input type="password" required minLength={8} value={form.password} onChange={set("password")} />
        </label>
        <button className="primary" disabled={busy}>
          {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
        </button>
        <button type="button" className="link" onClick={() => setMode(mode === "login" ? "register" : "login")}>
          {mode === "login" ? "New here? Create an account" : "Already have an account? Sign in"}
        </button>
      </form>
    </div>
  );
}
