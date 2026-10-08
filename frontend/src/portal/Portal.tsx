// Customer portal. Uses only /portal/* endpoints, which return the signed-in customer's own data and
// never internal fields (scores, tiers, agent reasoning, campaigns).
import { type FormEvent, useEffect, useRef, useState } from "react";
import { Link, Navigate, NavLink, Route, Routes, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, auth } from "../api";
import { Badge, Card, Empty, ErrorBanner, Notice, when } from "../components/ui";
import { useAction, useAsync } from "../components/useAsync";
import type { PortalClaim, PortalMessage, PortalNotification, PortalProduct, PortalService, WarrantyInfo } from "../types";

interface PortalMe {
  customer: { name: string; email: string; company: string; phone: string; preferences: Record<string, boolean> };
  business: { name: string; website: string };
}

export function WarrantyPill({ w, expires }: { w: WarrantyInfo; expires: string | null }) {
  const map = {
    ACTIVE: ["good", `Under warranty until ${expires}`],
    EXPIRING_SOON: ["warn", `Warranty expires ${expires} (${w.days_left} days left)`],
    EXPIRED: ["bad", `Warranty expired ${expires}`],
    NO_WARRANTY: ["muted", "No warranty"],
  }[w.status];
  return <span className={`badge ${map[0]}`}>{map[1]}</span>;
}

const NAV = [
  ["/portal", "Dashboard"], ["/portal/products", "My Products"], ["/portal/support", "Product Support"],
  ["/portal/warranty", "Warranty"], ["/portal/service", "Service & Repair"], ["/portal/conversations", "Messages"],
  ["/portal/notifications", "Notifications"],
] as const;

export default function Portal() {
  const me = useAsync(() => api.get<PortalMe>("/portal/me"));
  const navigate = useNavigate();
  return (
    <div className="layout portal">
      <aside className="sidebar portal-sidebar">
        <div className="brand">{me.data?.business.name ?? "Customer portal"}</div>
        <div className="muted small portal-tag">Customer portal · powered by GrowthOS</div>
        <nav>
          {NAV.map(([to, label]) => <NavLink key={to} to={to} end={to === "/portal"}>{label}</NavLink>)}
        </nav>
        <div className="sidebar-footer">
          {me.data && <><div className="org">{me.data.customer.name}</div><div className="muted small">{me.data.customer.company}</div></>}
          <button className="link" onClick={() => { auth.clear(); navigate("/login"); }}>Sign out</button>
        </div>
      </aside>
      <main className="content">
        <ErrorBanner error={me.error} />
        <Routes>
          <Route index element={<Home me={me.data} />} />
          <Route path="products" element={<Products />} />
          <Route path="products/:purchaseId" element={<ProductDetail />} />
          <Route path="support" element={<SupportPage />} />
          <Route path="warranty" element={<Warranty />} />
          <Route path="service" element={<Service />} />
          <Route path="conversations" element={<Conversations />} />
          <Route path="notifications" element={<Notifications />} />
          <Route path="*" element={<Navigate to="/portal" replace />} />
        </Routes>
      </main>
    </div>
  );
}

function Home({ me }: { me: PortalMe | null }) {
  const products = useAsync(() => api.get<PortalProduct[]>("/portal/products"));
  const appts = useAsync(() => api.get<PortalService[]>("/portal/appointments"));
  const notes = useAsync(() => api.get<PortalNotification[]>("/portal/notifications"));
  const claims = useAsync(() => api.get<PortalClaim[]>("/portal/warranty"));
  const upcoming = (appts.data ?? []).filter((a) => a.scheduled_for && new Date(a.scheduled_for) > new Date() && a.status !== "COMPLETED");
  return (
    <>
      <h1>Welcome{me ? `, ${me.customer.name.split(" ")[0]}` : ""}</h1>
      <p className="muted page-sub">Your products, warranty, support and service with {me?.business.name ?? "us"} in one place.</p>
      <div className="product-grid">
        {products.data?.map((p) => <ProductCard key={p.purchase_id} p={p} />)}
      </div>
      {products.data?.length === 0 && <Card><Empty>No products registered yet.</Empty></Card>}
      <div className="grid-2">
        <Card title="Upcoming appointments" actions={<Link to="/portal/service">Service →</Link>}>
          {upcoming.length === 0 ? <Empty>No upcoming appointments.</Empty> : upcoming.map((a) => (
            <p key={a.id}><b>{when(a.scheduled_for)}</b> — {a.product_name}<br /><span className="muted small">{a.note}</span></p>))}
          {(claims.data ?? []).filter((c) => !["COMPLETED", "REJECTED"].includes(c.status)).map((c) => (
            <p key={c.id} className="small">Warranty claim for {c.product_name}: <Badge value={c.status} /></p>))}
        </Card>
        <Card title="Latest notifications" actions={<Link to="/portal/notifications">All →</Link>}>
          {notes.data?.length === 0 && <Empty>Nothing new.</Empty>}
          <ul className="list">{notes.data?.slice(0, 5).map((n) => <li key={n.id}><Link to={n.link || "/portal"}>{n.title}</Link><span className="muted small">{when(n.created_at)}</span></li>)}</ul>
        </Card>
      </div>
    </>
  );
}

function ProductCard({ p }: { p: PortalProduct }) {
  return (
    <article className="product-card">
      <div className="product-icon" aria-hidden>{p.product_name.slice(0, 2).toUpperCase()}</div>
      <h3>{p.product_name}</h3>
      <p className="muted small">{p.quantity > 1 ? `${p.quantity} units · ` : ""}Purchased {p.purchased_at} · S/N {p.serial_number || "—"}</p>
      <WarrantyPill w={p.warranty} expires={p.warranty_expires_at} />
      <p className="small">Status: <Badge value={p.status} /></p>
      <div className="product-actions">
        <Link className="button" to={`/portal/products/${p.purchase_id}`}>View details</Link>
        <Link className="button primary-outline" to={`/portal/support?purchase=${p.purchase_id}`}>Ask AI</Link>
        <Link className="button" to={`/portal/conversations`}>Get support</Link>
        <Link className="button" to={`/portal/warranty?purchase=${p.purchase_id}`}>Claim warranty</Link>
        <Link className="button" to={`/portal/service?purchase=${p.purchase_id}`}>Book repair</Link>
      </div>
    </article>
  );
}

function Products() {
  const products = useAsync(() => api.get<PortalProduct[]>("/portal/products"));
  return (
    <>
      <h1>My Products</h1>
      <ErrorBanner error={products.error} />
      <div className="product-grid">{products.data?.map((p) => <ProductCard key={p.purchase_id} p={p} />)}</div>
      {products.data?.length === 0 && <Card><Empty>No products registered yet.</Empty></Card>}
    </>
  );
}

interface ProductDetailData extends PortalProduct {
  documents: { id: string; title: string; doc_type: string; content: string }[];
  warranty_claims: PortalClaim[];
  service_requests: PortalService[];
}

function ProductDetail() {
  const { purchaseId } = useParams();
  const d = useAsync(() => api.get<ProductDetailData>(`/portal/products/${purchaseId}`), [purchaseId]);
  if (d.error) return <ErrorBanner error={d.error} />;
  if (!d.data) return <p className="muted">Loading…</p>;
  const p = d.data;
  return (
    <>
      <div className="muted small"><Link to="/portal/products">My Products</Link></div>
      <h1>{p.product_name}</h1>
      <p className="muted">{p.description}</p>
      <div className="grid-2">
        <Card title="Product & warranty">
          <dl className="facts">
            <dt>Purchased</dt><dd>{p.purchased_at}</dd>
            <dt>Serial number</dt><dd>{p.serial_number || "Not available"}</dd>
            <dt>Quantity</dt><dd>{p.quantity}</dd>
            <dt>Status</dt><dd><Badge value={p.status} /></dd>
            <dt>Warranty</dt><dd><WarrantyPill w={p.warranty} expires={p.warranty_expires_at} /></dd>
          </dl>
          <div className="actions">
            <Link className="button" to={`/portal/warranty?purchase=${p.purchase_id}`}>Claim warranty</Link>
            <Link className="button" to={`/portal/service?purchase=${p.purchase_id}`}>Book repair</Link>
          </div>
          <h3>Documentation</h3>
          {p.documents.length === 0 ? <p className="muted small">No documentation available.</p> : p.documents.map((doc) => (
            <details key={doc.id}><summary>{doc.title} <span className="muted small">({doc.doc_type.replace("_", " ")})</span></summary><pre className="doc">{doc.content}</pre></details>
          ))}
        </Card>
        <SupportChat purchaseId={p.purchase_id} productName={p.product_name} />
      </div>
    </>
  );
}

function SupportChat({ purchaseId, productName }: { purchaseId: string | null; productName?: string }) {
  const history = useAsync(() => api.get<PortalMessage[]>(`/portal/support/history${purchaseId ? `?purchase_id=${purchaseId}` : ""}`), [purchaseId]);
  const [q, setQ] = useState("");
  const [canEscalate, setCanEscalate] = useState(false);
  const action = useAction();
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => end.current?.scrollIntoView({ block: "nearest" }), [history.data]);

  async function ask(e: FormEvent) {
    e.preventDefault();
    const res = await action.run("ask", () => api.post<{ can_escalate: boolean }>("/portal/support/ask", { question: q, purchase_id: purchaseId }));
    if (res) { setQ(""); setCanEscalate(res.can_escalate); history.reload(); }
  }
  return (
    <Card title={`Ask AI${productName ? ` about ${productName}` : ""}`} actions={<span className="muted small">answers only from official documentation</span>}>
      <div className="chat">
        {history.data?.length === 0 && <p className="muted small">Ask about setup, usage, maintenance or troubleshooting.</p>}
        {history.data?.map((m) => (
          <div key={m.id} className={`bubble from-${m.sender}`}>
            <div className="bubble-meta">{m.sender === "ai" ? "Support AI" : "You"}</div>
            <div className="bubble-body">{m.body}</div>
            {m.sources.length > 0 && <div className="bubble-sources">Source: {m.sources.map((s) => `${s.title}${s.section ? ` › ${s.section}` : ""}`).join("; ")}</div>}
          </div>
        ))}
        <div ref={end} />
      </div>
      <ErrorBanner error={action.error} />
      {canEscalate && <div className="banner info"><span>Need a person? <Link to="/portal/conversations">Message the support team →</Link></span></div>}
      <form className="inline-form" onSubmit={ask}>
        <input required placeholder="e.g. What does error E2 mean?" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="primary" disabled={!!action.busy}>{action.busy ? "Thinking…" : "Ask"}</button>
      </form>
    </Card>
  );
}

function SupportPage() {
  const [params, setParams] = useSearchParams();
  const products = useAsync(() => api.get<PortalProduct[]>("/portal/products"));
  const selected = params.get("purchase") ?? products.data?.[0]?.purchase_id ?? null;
  const product = products.data?.find((p) => p.purchase_id === selected);
  return (
    <>
      <h1>Product Support</h1>
      <p className="muted page-sub">The support assistant only uses your product's documentation. If the answer isn't there, it will say so and you can message our team.</p>
      <div className="actions" style={{ marginBottom: 12 }}>
        {products.data?.map((p) => <button key={p.purchase_id} className={p.purchase_id === selected ? "primary" : ""} onClick={() => setParams({ purchase: p.purchase_id })}>{p.product_name}</button>)}
      </div>
      {selected && <SupportChat key={selected} purchaseId={selected} productName={product?.product_name} />}
    </>
  );
}

function Warranty() {
  const [params] = useSearchParams();
  const products = useAsync(() => api.get<PortalProduct[]>("/portal/products"));
  const claims = useAsync(() => api.get<PortalClaim[]>("/portal/warranty"));
  const [form, setForm] = useState({ purchase_id: params.get("purchase") ?? "", issue: "" });
  const action = useAction();
  const selected = form.purchase_id || products.data?.[0]?.purchase_id || "";
  const product = products.data?.find((p) => p.purchase_id === selected);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (await action.run("claim", () => api.post("/portal/warranty", { purchase_id: selected, issue: form.issue }), "Claim submitted. Our team will review it.")) {
      setForm({ ...form, issue: "" });
      claims.reload();
    }
  }
  return (
    <>
      <h1>Warranty</h1>
      <div className="grid-2">
        <Card title="Submit a warranty claim">
          <ErrorBanner error={action.error} />
          <Notice message={action.notice} />
          <form className="stack" onSubmit={submit}>
            <label>Product
              <select value={selected} onChange={(e) => setForm({ ...form, purchase_id: e.target.value })}>
                {products.data?.map((p) => <option key={p.purchase_id} value={p.purchase_id}>{p.product_name} (S/N {p.serial_number || "—"})</option>)}
              </select>
            </label>
            {product && <p><WarrantyPill w={product.warranty} expires={product.warranty_expires_at} /></p>}
            <label>Describe the issue<textarea rows={4} required minLength={5} value={form.issue} onChange={(e) => setForm({ ...form, issue: e.target.value })} /></label>
            <button className="primary" disabled={!!action.busy || !selected}>Submit claim</button>
            <p className="muted small">Every claim is reviewed by our team. You'll see the decision here.</p>
          </form>
        </Card>
        <Card title="Your claims">
          {claims.data?.length === 0 && <Empty>No claims.</Empty>}
          {claims.data?.map((c) => (
            <div key={c.id} className="claim-row">
              <div className="row-head"><b>{c.product_name}</b><Badge value={c.status} /></div>
              <p className="small">{c.issue}</p>
              {c.resolution_note && <p className="small"><b>Update:</b> {c.resolution_note}</p>}
              <p className="muted small">Submitted {when(c.created_at)}</p>
            </div>
          ))}
        </Card>
      </div>
    </>
  );
}

function Service() {
  const [params] = useSearchParams();
  const products = useAsync(() => api.get<PortalProduct[]>("/portal/products"));
  const reqs = useAsync(() => api.get<PortalService[]>("/portal/service"));
  const [form, setForm] = useState({ purchase_id: params.get("purchase") ?? "", issue: "", preferred_date: "", preferred_time: "morning", contact_phone: "" });
  const action = useAction();
  const selected = form.purchase_id || products.data?.[0]?.purchase_id || "";
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (await action.run("svc", () => api.post("/portal/service", { ...form, purchase_id: selected, preferred_date: form.preferred_date || null }), "Request sent. We'll confirm your appointment.")) {
      setForm({ ...form, issue: "" });
      reqs.reload();
    }
  }
  return (
    <>
      <h1>Service &amp; Repair</h1>
      <div className="grid-2">
        <Card title="Book a service or repair">
          <ErrorBanner error={action.error} />
          <Notice message={action.notice} />
          <form className="stack" onSubmit={submit}>
            <label>Product
              <select value={selected} onChange={(e) => setForm({ ...form, purchase_id: e.target.value })}>
                {products.data?.map((p) => <option key={p.purchase_id} value={p.purchase_id}>{p.product_name}</option>)}
              </select>
            </label>
            <label>What do you need?<textarea rows={3} required minLength={5} value={form.issue} onChange={(e) => setForm({ ...form, issue: e.target.value })} /></label>
            <div className="inline-form">
              <label>Preferred date<input type="date" value={form.preferred_date} onChange={(e) => setForm({ ...form, preferred_date: e.target.value })} /></label>
              <label>Time<select value={form.preferred_time} onChange={(e) => setForm({ ...form, preferred_time: e.target.value })}><option>morning</option><option>afternoon</option><option>any time</option></select></label>
              <label>Phone<input value={form.contact_phone} onChange={(e) => setForm({ ...form, contact_phone: e.target.value })} /></label>
            </div>
            <button className="primary" disabled={!!action.busy || !selected}>Request appointment</button>
          </form>
        </Card>
        <Card title="Your requests & appointments">
          {reqs.data?.length === 0 && <Empty>No requests.</Empty>}
          {reqs.data?.map((s) => (
            <div key={s.id} className="claim-row">
              <div className="row-head"><b>{s.product_name}</b><Badge value={s.status} /></div>
              <p className="small">{s.issue}</p>
              {s.scheduled_for ? <p className="small"><b>Appointment:</b> {when(s.scheduled_for)}</p> : <p className="small muted">Preferred: {s.preferred_date ?? "any date"} {s.preferred_time}</p>}
              {s.note && <p className="small"><b>Note:</b> {s.note}</p>}
              {["PENDING_CONFIRMATION", "CONFIRMED", "RESCHEDULED"].includes(s.status) && (
                <button className="link" onClick={async () => { await action.run("cancel", () => api.post(`/portal/service/${s.id}/cancel`)); reqs.reload(); }}>Cancel request</button>
              )}
            </div>
          ))}
        </Card>
      </div>
    </>
  );
}

function Conversations() {
  const msgs = useAsync(() => api.get<PortalMessage[]>("/portal/conversations"));
  const [body, setBody] = useState("");
  const action = useAction();
  async function send(e: FormEvent) {
    e.preventDefault();
    if (await action.run("send", () => api.post("/portal/conversations", { body }))) { setBody(""); msgs.reload(); }
  }
  return (
    <>
      <h1>Messages</h1>
      <p className="muted page-sub">Write to our team. Simple questions may be answered instantly from our documentation; everything else goes to a person.</p>
      <Card>
        <div className="chat tall">
          {msgs.data?.length === 0 && <Empty>No messages yet.</Empty>}
          {msgs.data?.map((m) => (
            <div key={m.id} className={`bubble from-${m.sender}`}>
              <div className="bubble-meta">{m.sender === "ai" ? "Automated assistant" : m.sender === "business" ? "Support team" : "You"} · {when(m.created_at)}</div>
              <div className="bubble-body">{m.body}</div>
              {m.sources.length > 0 && <div className="bubble-sources">Source: {m.sources.map((s) => s.title).join("; ")}</div>}
            </div>
          ))}
        </div>
        <ErrorBanner error={action.error} />
        <form className="inline-form" onSubmit={send}>
          <input required placeholder="Type your message…" value={body} onChange={(e) => setBody(e.target.value)} />
          <button className="primary" disabled={!!action.busy}>Send</button>
        </form>
      </Card>
    </>
  );
}

function Notifications() {
  const notes = useAsync(() => api.get<PortalNotification[]>("/portal/notifications"));
  const prefs = useAsync(() => api.get<PortalMe>("/portal/me"));
  const action = useAction();
  const on = prefs.data?.customer.preferences.lifecycle_messages !== false;
  return (
    <>
      <div className="page-header">
        <h1>Notifications</h1>
        <button onClick={async () => { await action.run("read", () => api.post("/portal/notifications/read-all")); notes.reload(); }}>Mark all read</button>
      </div>
      <Card>
        {notes.data?.length === 0 && <Empty>No notifications.</Empty>}
        <ul className="list">
          {notes.data?.map((n) => (
            <li key={n.id} className={n.read ? "" : "unread"}>
              <div><Link to={n.link || "/portal"}><b>{n.title}</b></Link>{n.body && <div className="small muted">{n.body}</div>}</div>
              <span className="muted small">{when(n.created_at)}</span>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Preferences">
        <label className="checkbox">
          <input type="checkbox" checked={on} onChange={async (e) => { await action.run("pref", () => api.patch("/portal/preferences", { lifecycle_messages: e.target.checked })); prefs.reload(); }} />
          Send me helpful product follow-ups (setup tips, check-ins, warranty reminders)
        </label>
      </Card>
    </>
  );
}
