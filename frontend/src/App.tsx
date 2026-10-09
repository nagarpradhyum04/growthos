import { useEffect, useState } from "react";
import { Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api, auth } from "./api";
import type { Me, SystemStatus } from "./types";
import Analytics from "./pages/Analytics";
import Approvals from "./pages/Approvals";
import Care from "./pages/Care";
import Customers, { CustomerView } from "./pages/Customers";
import Inbox from "./pages/Inbox";
import Memory from "./pages/Memory";
import Products from "./pages/Products";
import Workflows, { WorkflowView } from "./pages/Workflows";
import Campaigns from "./pages/Campaigns";
import Dashboard from "./pages/Dashboard";
import EmailReview from "./pages/EmailReview";
import LeadDetail from "./pages/LeadDetail";
import Leads from "./pages/Leads";
import Login from "./pages/Login";
import Replies from "./pages/Replies";
import Settings from "./pages/Settings";
import SocialStudio from "./pages/SocialStudio";

const NAV: [string, string][] = [
  ["/", "Command Center"],
  ["/approvals", "Approvals"],
  ["/workflows", "Workflows & Trace"],
  ["§Growth", ""],
  ["/leads", "Leads"],
  ["/campaigns", "Campaigns"],
  ["/emails", "Email Review"],
  ["/inbox", "Inbox"],
  ["/social", "Social Studio"],
  ["§Customer care", ""],
  ["/customers", "Customers"],
  ["/care", "Warranty & Service"],
  ["/products", "Products & Knowledge"],
  ["§Intelligence", ""],
  ["/memory", "Shared Memory"],
  ["/analytics", "Analytics"],
  ["/settings", "Settings & Rules"],
];

/** Top status bar. Every value comes from /system/status (counted from the database or configuration). */
function StatusBar({ path }: { path: string }) {
  const [st, setSt] = useState<SystemStatus | null>(null);
  const [offline, setOffline] = useState(false);
  useEffect(() => {
    let alive = true;
    const load = () => api.get<SystemStatus>("/system/status")
      .then((s) => { if (alive) { setSt(s); setOffline(false); } })
      .catch(() => { if (alive) setOffline(true); });
    void load();
    const t = window.setInterval(load, 15000);
    return () => { alive = false; window.clearInterval(t); };
  }, [path]);
  const active = st?.agents_active_10m.length ?? 0;
  const tone = offline ? "warn" : st && (st.workflows_running || active) ? "" : "idle";
  return (
    <div className="statusbar" role="status">
      <div className="sb-left">
        <span><i className={`sb-dot ${tone}`} />
          {offline ? "System status: API unreachable"
            : !st ? "System status: …"
            : <>System status: <b>{st.workflows_running ? `${st.workflows_running} workflow${st.workflows_running > 1 ? "s" : ""} running` : "idle"}</b>
              {" / "}{active} agent{active === 1 ? "" : "s"} active (10 min) / shared memory: {st.memory_entries} entries</>}
        </span>
      </div>
      {st && (
        <div className="sb-right">
          <span>Orchestrator: <b>{st.jobs_waiting_for_worker ? "worker not picking up jobs" : "online"}</b></span>
          <span title="can_send() and the policy layer run on every send; this counts actions they blocked in the last 7 days">
            Policy gate: <b>enforced</b> · {st.blocked_by_policy_7d} blocked (7d)</span>
          <span>LLM: {st.providers.llm} · Media: {st.providers.media === "gemini" ? "Nano Banana / Veo" : "mock"}</span>
        </div>
      )}
    </div>
  );
}

function Shell() {
  const [me, setMe] = useState<Me | null>(null);
  const [pending, setPending] = useState(0);
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    api.get<Me>("/auth/me").then(setMe).catch(() => undefined);
  }, []);
  useEffect(() => {
    api.get<unknown[]>("/approvals?status=PENDING").then((a) => setPending(a.length)).catch(() => undefined);
  }, [location.pathname]);

  return (
    <div className="app-frame">
      <StatusBar path={location.pathname} />
      <div className="layout">
        <aside className="sidebar">
          <div className="brand-block">
            <div className="brand">GrowthOS<span className="brand-sub">Architectural AI OS</span></div>
          </div>
          <nav>
            {NAV.map(([to, label]) =>
              to.startsWith("§") ? (
                <div key={to} className="nav-section">{to.slice(1)}</div>
              ) : (
                <NavLink key={to} to={to} end={to === "/"}>
                  {label}
                  {to === "/approvals" && pending > 0 && <span className="nav-count">{pending}</span>}
                </NavLink>
              ),
            )}
          </nav>
          <div className="sidebar-footer">
            {me && (
              <>
                <div className="org">{me.organization.name}</div>
                <div className="muted small">{me.user.email}</div>
              </>
            )}
            <button
              className="signout"
              onClick={() => {
                auth.clear();
                navigate("/login");
              }}
            >
              Sign out
            </button>
          </div>
        </aside>
        <main className="content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/leads" element={<Leads />} />
            <Route path="/leads/:id" element={<LeadDetail />} />
            <Route path="/campaigns" element={<Campaigns />} />
            <Route path="/emails" element={<EmailReview />} />
            <Route path="/emails/:id" element={<EmailReview />} />
            <Route path="/replies" element={<Replies />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/approvals" element={<Approvals />} />
            <Route path="/workflows" element={<Workflows />} />
            <Route path="/workflows/:id" element={<WorkflowView />} />
            <Route path="/inbox" element={<Inbox />} />
            <Route path="/social" element={<SocialStudio />} />
            <Route path="/customers" element={<Customers />} />
            <Route path="/customers/:id" element={<CustomerView />} />
            <Route path="/products" element={<Products />} />
            <Route path="/care" element={<Care />} />
            <Route path="/memory" element={<Memory />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

// Reads the token at render time (not when App first rendered), so login/logout take effect immediately.
// Business-owner app only. Customers use the separate customer portal app (see vite.portal.config.ts).
function RequireAuth() {
  return auth.token && auth.role === "owner" ? <Shell /> : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/*" element={<RequireAuth />} />
    </Routes>
  );
}
