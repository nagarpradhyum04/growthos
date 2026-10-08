import { useEffect, useState } from "react";
import { Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api, auth } from "./api";
import type { Me } from "./types";
import Portal from "./portal/Portal";
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

const NAV: [string, string][] = [
  ["/", "Command Center"],
  ["/approvals", "Approvals"],
  ["/workflows", "Workflows & Trace"],
  ["§Growth", ""],
  ["/leads", "Leads"],
  ["/campaigns", "Campaigns"],
  ["/emails", "Email Review"],
  ["/inbox", "Inbox"],
  ["§Customers", ""],
  ["/customers", "Customers"],
  ["/care", "Warranty & Service"],
  ["/products", "Products & Knowledge"],
  ["§Intelligence", ""],
  ["/memory", "Shared Memory"],
  ["/analytics", "Analytics"],
  ["/settings", "Settings & Rules"],
];

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
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          Growth<span>OS</span>
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
            className="link"
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
          <Route path="/customers" element={<Customers />} />
          <Route path="/customers/:id" element={<CustomerView />} />
          <Route path="/products" element={<Products />} />
          <Route path="/care" element={<Care />} />
          <Route path="/memory" element={<Memory />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

// Reads the token at render time (not when App first rendered), so login/logout take effect immediately.
function RequireAuth() {
  if (!auth.token) return <Navigate to="/login" replace />;
  return auth.role === "customer" ? <Navigate to="/portal" replace /> : <Shell />;
}

function RequireCustomer() {
  if (!auth.token) return <Navigate to="/login" replace />;
  return auth.role === "customer" ? <Portal /> : <Navigate to="/" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/portal/*" element={<RequireCustomer />} />
      <Route path="/*" element={<RequireAuth />} />
    </Routes>
  );
}
