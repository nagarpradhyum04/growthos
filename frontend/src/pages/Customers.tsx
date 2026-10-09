import { type FormEvent, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { TierBadge } from "../components/trace";
import { Badge, Card, Empty, ErrorBanner, Notice, when } from "../components/ui";
import { useAction, useAsync } from "../components/useAsync";
import type { CustomerDetail, CustomerRow, Me, ProductRow, WarrantyInfo } from "../types";

export function WarrantyBadge({ w, expires }: { w: WarrantyInfo; expires: string | null }) {
  const text = {
    ACTIVE: `Warranty until ${expires}`,
    EXPIRING_SOON: `Expires ${expires} (${w.days_left} days)`,
    EXPIRED: `Expired ${expires}`,
    NO_WARRANTY: "No warranty",
  }[w.status];
  const tone = { ACTIVE: "good", EXPIRING_SOON: "warn", EXPIRED: "bad", NO_WARRANTY: "muted" }[w.status];
  return <span className={`badge ${tone}`}>{text}</span>;
}

export function BusinessIdBanner() {
  const me = useAsync(() => api.get<Me>("/auth/me"));
  const [copied, setCopied] = useState(false);
  const org = me.data?.organization;
  if (!org) return null;
  return (
    <div className="business-id-banner">
      <div>
        <div className="muted small">Your Business ID — share it with customers</div>
        <div className="business-id">{org.business_code}</div>
      </div>
      <div className="small">
        Customers sign in at <a href={org.portal_url} target="_blank" rel="noreferrer">{org.portal_url}</a> with this
        Business ID and the email you registered for them. An access agent verifies the email and sends a one-time code.
      </div>
      <button onClick={() => { void navigator.clipboard?.writeText(org.business_code); setCopied(true); }}>{copied ? "Copied" : "Copy ID"}</button>
    </div>
  );
}

export default function Customers() {
  const list = useAsync(() => api.get<CustomerRow[]>("/customers"));
  const [form, setForm] = useState({ name: "", email: "", company: "", phone: "" });
  const action = useAction();
  const navigate = useNavigate();

  async function create(e: FormEvent) {
    e.preventDefault();
    const c = await action.run("create", () => api.post<CustomerRow>("/customers", form));
    if (c) navigate(`/customers/${c.id}`);
  }

  return (
    <>
      <h1>Customers</h1>
      <p className="muted page-sub">Your customer list. Customers come from converted leads or are added directly; they use their own portal app, not this one.</p>
      <BusinessIdBanner />
      <ErrorBanner error={list.error ?? action.error} />
      <Card>
        {list.data?.length === 0 && <Empty>No customers yet. Convert a lead or add one below.</Empty>}
        {!!list.data?.length && (
          <table>
            <thead><tr><th>Customer</th><th>Company</th><th>Source</th><th>Portal sign-in</th><th>Since</th></tr></thead>
            <tbody>
              {list.data.map((c) => (
                <tr key={c.id} className="clickable" onClick={() => navigate(`/customers/${c.id}`)}>
                  <td><Link to={`/customers/${c.id}`}>{c.name}</Link><div className="muted small">{c.email}</div></td>
                  <td>{c.company || "—"}</td>
                  <td className="small">{c.lead_id ? <Link to={`/leads/${c.lead_id}`} onClick={(e) => e.stopPropagation()}>Converted lead</Link> : "Added manually"}</td>
                  <td>{c.portal_access ? <Badge value="ACTIVE" /> : <span className="muted small">Not signed in yet</span>}</td>
                  <td className="small muted">{when(c.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <Card title="Add customer">
        <form className="form-grid" onSubmit={create}>
          <label>Name<input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
          <label>Email<input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
          <label>Company<input value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} /></label>
          <label>Phone<input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></label>
          <div className="span-2"><button className="primary" disabled={!!action.busy}>Add customer</button></div>
        </form>
      </Card>
    </>
  );
}

export function CustomerView() {
  const { id } = useParams();
  const c = useAsync(() => api.get<CustomerDetail>(`/customers/${id}`), [id]);
  const products = useAsync(() => api.get<ProductRow[]>("/products"));
  const [purchase, setPurchase] = useState({ product_id: "", purchased_at: new Date().toISOString().slice(0, 10), quantity: 1, serial_number: "", order_value: "" });
  const [reply, setReply] = useState("");
  const action = useAction();
  const d = c.data;

  async function run(label: string, fn: () => Promise<unknown>, ok: string) {
    if (await action.run(label, fn, ok)) c.reload();
  }

  if (c.error) return <ErrorBanner error={c.error} />;
  if (!d) return <p className="muted">Loading…</p>;
  const business = d.messages.filter((m) => m.channel === "business");
  return (
    <>
      <div className="page-header">
        <div>
          <div className="muted small"><Link to="/customers">Customers</Link></div>
          <h1>{d.name} <Badge value={d.status} /></h1>
          <div className="muted">{d.company} · {d.email} {d.phone && `· ${d.phone}`}</div>
        </div>
        {d.lead_id && <Link className="button" to={`/leads/${d.lead_id}`}>Original lead →</Link>}
      </div>
      <ErrorBanner error={action.error} onClose={() => action.setError(null)} />
      <Notice message={action.notice} />
      <div className="grid-2">
        <Card title="Products owned">
          {d.purchases.length === 0 && <Empty>No purchases recorded.</Empty>}
          <ul className="list">
            {d.purchases.map((p) => (
              <li key={p.id}>
                <div><b>{p.quantity} × {p.product_name}</b><div className="muted small">Bought {p.purchased_at} · S/N {p.serial_number || "—"}</div></div>
                <WarrantyBadge w={p.warranty} expires={p.warranty_expires_at} />
              </li>
            ))}
          </ul>
          <form className="inline-form" onSubmit={(e) => { e.preventDefault(); void run("purchase", () => api.post(`/customers/${id}/purchases`, { ...purchase, product_id: purchase.product_id || products.data?.[0]?.id, order_value: purchase.order_value ? Number(purchase.order_value) : null }), "Purchase recorded."); }}>
            <select value={purchase.product_id} onChange={(e) => setPurchase({ ...purchase, product_id: e.target.value })}>
              {products.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <input type="date" value={purchase.purchased_at} onChange={(e) => setPurchase({ ...purchase, purchased_at: e.target.value })} />
            <input type="number" min={1} value={purchase.quantity} onChange={(e) => setPurchase({ ...purchase, quantity: Number(e.target.value) })} style={{ width: 70 }} />
            <input placeholder="Serial no." value={purchase.serial_number} onChange={(e) => setPurchase({ ...purchase, serial_number: e.target.value })} />
            <button disabled={!products.data?.length}>Add purchase</button>
          </form>
        </Card>
        <Card title="Customer portal">
          <p className="small">{d.portal_access ? <><Badge value="ACTIVE" /> {d.name} has signed in to the portal.</>
            : <span className="muted">{d.name} hasn't signed in yet.</span>}</p>
          <p className="small muted">They sign in on the customer portal with your Business ID and <b>{d.email}</b>. Only emails on your customer list are accepted.</p>
          <p className="small muted">Lifecycle messages: {d.preferences.lifecycle_messages === false ? "opted out" : "on"} (customer-controlled)</p>
          <h3>Warranty claims</h3>
          {d.warranty_claims.length ? <ul className="list">{d.warranty_claims.map((w) => <li key={w.id}><span className="small">{w.issue.slice(0, 70)}</span><Badge value={w.status} /></li>)}</ul> : <p className="muted small">None</p>}
          <h3>Service requests</h3>
          {d.service_requests.length ? <ul className="list">{d.service_requests.map((s) => <li key={s.id}><span className="small">{s.issue.slice(0, 70)}</span><Badge value={s.status} /></li>)}</ul> : <p className="muted small">None</p>}
          <Link to="/care">Manage warranty &amp; service →</Link>
        </Card>
      </div>
      <div className="grid-2">
        <Card title="Conversation">
          {business.length === 0 && <Empty>No messages yet.</Empty>}
          <div className="chat">
            {business.map((m) => (
              <div key={m.id} className={`bubble from-${m.sender}`}>
                <div className="bubble-meta">{m.sender === "ai" ? "GrowthOS AI" : m.sender === "business" ? "You" : d.name} · {when(m.created_at)} {m.sender === "customer" && <TierBadge tier={m.tier} />}</div>
                <div className="bubble-body">{m.body}</div>
              </div>
            ))}
          </div>
          <form className="stack" onSubmit={(e) => { e.preventDefault(); void run("reply", () => api.post(`/customers/${id}/messages`, { body: reply }), "Message sent."); setReply(""); }}>
            <textarea rows={2} required placeholder="Write to the customer…" value={reply} onChange={(e) => setReply(e.target.value)} />
            <button>Send</button>
          </form>
        </Card>
        <Card title="Shared memory" actions={<span className="muted small">what agents know</span>}>
          {d.memory.length === 0 && <Empty>No memory entries.</Empty>}
          <ul className="memory-list">
            {d.memory.map((m, i) => (
              <li key={i}><span className={`mem-cat cat-${m.category}`}>{m.category}</span> {m.content}<div className="muted small">by {m.source} · {when(m.updated_at)}</div></li>
            ))}
          </ul>
        </Card>
      </div>
    </>
  );
}
