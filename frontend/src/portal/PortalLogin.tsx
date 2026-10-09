import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, auth, describeError } from "../api";
import { ErrorBanner } from "../components/ui";

interface RequestOut { request_id: string; message: string; dev_code?: string }

/** Step 1: Business ID + email -> the Access Agent checks the request. Step 2: one-time code -> portal. */
export default function PortalLogin() {
  const [businessId, setBusinessId] = useState("");
  const [email, setEmail] = useState("");
  const [request, setRequest] = useState<RequestOut | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  async function requestAccess(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setRequest(await api.post<RequestOut>("/portal-auth/request", { business_id: businessId, email }));
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  async function verify(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const out = await api.post<{ access_token: string }>("/portal-auth/verify", { request_id: request!.request_id, code });
      auth.set(out.access_token, "customer");
      navigate("/portal");
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-page portal-auth">
      {!request ? (
        <form className="card auth-card" onSubmit={requestAccess}>
          <div className="brand large">Customer <span>Portal</span></div>
          <p className="muted">Your products, warranty, support and service in one place. Sign in with the Business ID your supplier gave you.</p>
          <ErrorBanner error={error} />
          <label>Business ID
            <input required placeholder="GOS-XXXXXX" value={businessId} onChange={(e) => setBusinessId(e.target.value.toUpperCase())} />
          </label>
          <label>Your email
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <button className="primary" disabled={busy}>{busy ? "Checking…" : "Request access"}</button>
          <p className="muted small">An access agent checks that your email is registered with this business, then emails you a one-time sign-in code.</p>
        </form>
      ) : (
        <form className="card auth-card" onSubmit={verify}>
          <div className="brand large">Check your <span>email</span></div>
          <p className="muted">{request.message}</p>
          {request.dev_code && (
            <div className="banner info"><span>Demo mode (no real email is sent): your code is <b>{request.dev_code}</b></span></div>
          )}
          <ErrorBanner error={error} />
          <label>6-digit code
            <input required inputMode="numeric" pattern="\d{6}" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} autoFocus />
          </label>
          <button className="primary" disabled={busy || code.length !== 6}>{busy ? "Verifying…" : "Sign in"}</button>
          <button type="button" className="link" onClick={() => { setRequest(null); setCode(""); }}>Use a different Business ID or email</button>
        </form>
      )}
    </div>
  );
}
