import { useEffect, useState } from "react";
import { Navigate, NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { api, auth } from "./api";
import type { Me } from "./types";
import Analytics from "./pages/Analytics";
import Campaigns from "./pages/Campaigns";
import Dashboard from "./pages/Dashboard";
import EmailReview from "./pages/EmailReview";
import LeadDetail from "./pages/LeadDetail";
import Leads from "./pages/Leads";
import Login from "./pages/Login";
import Replies from "./pages/Replies";
import Settings from "./pages/Settings";

const NAV = [
  ["/", "Dashboard"],
  ["/leads", "Leads"],
  ["/campaigns", "Campaigns"],
  ["/emails", "Email Review"],
  ["/replies", "Replies"],
  ["/analytics", "Analytics"],
  ["/settings", "Business Profile"],
] as const;

function Shell() {
  const [me, setMe] = useState<Me | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    api.get<Me>("/auth/me").then(setMe).catch(() => undefined);
  }, []);

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          Growth<span>OS</span>
        </div>
        <nav>
          {NAV.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/"}>
              {label}
            </NavLink>
          ))}
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
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

// Reads the token at render time (not when App first rendered), so login/logout take effect immediately.
function RequireAuth() {
  return auth.token ? <Shell /> : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/*" element={<RequireAuth />} />
    </Routes>
  );
}
