import { type FormEvent, useState } from "react";
import { api } from "../api";
import { Card, Empty, ErrorBanner, Notice } from "../components/ui";
import { useAction, useAsync } from "../components/useAsync";
import type { KnowledgeDoc, ProductRow } from "../types";

interface Hit { chunk_id: string; title: string; heading: string; doc_type: string; text: string; score: number }

export default function Products() {
  const products = useAsync(() => api.get<ProductRow[]>("/products"));
  const docs = useAsync(() => api.get<KnowledgeDoc[]>("/knowledge"));
  const [p, setP] = useState({ name: "", sku: "", category: "", description: "", warranty_months: 12, price: "" });
  const [doc, setDoc] = useState({ id: "", title: "", doc_type: "manual", product_id: "", content: "" });
  const [query, setQuery] = useState({ q: "", product_id: "" });
  const [hits, setHits] = useState<Hit[] | null>(null);
  const action = useAction();
  const productName = new Map((products.data ?? []).map((x) => [x.id, x.name]));

  async function addProduct(e: FormEvent) {
    e.preventDefault();
    if (await action.run("product", () => api.post("/products", { ...p, price: p.price ? Number(p.price) : null }), "Product added.")) {
      setP({ name: "", sku: "", category: "", description: "", warranty_months: 12, price: "" });
      products.reload();
    }
  }
  async function saveDoc(e: FormEvent) {
    e.preventDefault();
    const body = { title: doc.title, doc_type: doc.doc_type, content: doc.content, product_id: doc.product_id || null };
    const ok = await action.run("doc", () => doc.id ? api.put(`/knowledge/${doc.id}`, body) : api.post("/knowledge", body),
      "Document saved and indexed for retrieval.");
    if (ok) {
      setDoc({ id: "", title: "", doc_type: "manual", product_id: "", content: "" });
      docs.reload();
    }
  }
  async function search(e: FormEvent) {
    e.preventDefault();
    const res = await action.run("search", () => api.post<Hit[]>("/knowledge/search", { query: query.q, product_id: query.product_id || null }));
    if (res) setHits(res);
  }

  return (
    <>
      <h1>Products &amp; Knowledge Base</h1>
      <p className="muted page-sub">The Product Support AI answers customers <b>only</b> from these documents. If something isn't written here, it says it can't find it.</p>
      <ErrorBanner error={products.error ?? docs.error ?? action.error} onClose={() => action.setError(null)} />
      <Notice message={action.notice} />
      <div className="grid-2">
        <Card title="Products">
          {products.data?.length === 0 && <Empty>No products yet.</Empty>}
          <ul className="list">
            {products.data?.map((x) => (
              <li key={x.id}><div><b>{x.name}</b> <span className="muted small">{x.sku}</span><div className="muted small">{x.description}</div></div>
                <span className="small">{x.warranty_months ? `${x.warranty_months}-month warranty` : "No warranty"}</span></li>
            ))}
          </ul>
          <form className="form-grid" onSubmit={addProduct}>
            <label>Name<input required value={p.name} onChange={(e) => setP({ ...p, name: e.target.value })} /></label>
            <label>SKU<input value={p.sku} onChange={(e) => setP({ ...p, sku: e.target.value })} /></label>
            <label>Category<input value={p.category} onChange={(e) => setP({ ...p, category: e.target.value })} /></label>
            <label>Warranty (months)<input type="number" min={0} value={p.warranty_months} onChange={(e) => setP({ ...p, warranty_months: Number(e.target.value) })} /></label>
            <label className="span-2">Description<input value={p.description} onChange={(e) => setP({ ...p, description: e.target.value })} /></label>
            <div className="span-2"><button className="primary">Add product</button></div>
          </form>
        </Card>
        <Card title="Test retrieval" actions={<span className="muted small">exactly what the AI would be given</span>}>
          <form className="inline-form" onSubmit={search}>
            <input required placeholder="e.g. how often do I replace the filter?" value={query.q} onChange={(e) => setQuery({ ...query, q: e.target.value })} />
            <select value={query.product_id} onChange={(e) => setQuery({ ...query, product_id: e.target.value })}>
              <option value="">All products</option>
              {products.data?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
            <button>Search</button>
          </form>
          {hits && hits.length === 0 && <p className="unknown small">No relevant excerpt — the Support AI would answer “I couldn't find that information…”.</p>}
          {hits?.map((h) => (
            <div key={h.chunk_id} className="excerpt">
              <div className="small"><b>{h.title}</b>{h.heading && ` › ${h.heading}`} <span className="muted">score {h.score}</span></div>
              <p className="small">{h.text}</p>
            </div>
          ))}
        </Card>
      </div>
      <Card title="Knowledge documents">
        {docs.data?.length === 0 && <Empty>No documents yet.</Empty>}
        <table>
          <thead><tr><th>Title</th><th>Type</th><th>Product</th><th className="num">Chunks</th><th /></tr></thead>
          <tbody>
            {docs.data?.map((d) => (
              <tr key={d.id}>
                <td>{d.title}</td><td className="small">{d.doc_type.replace("_", " ")}</td>
                <td className="small">{d.product_id ? productName.get(d.product_id) : "All products"}</td>
                <td className="num">{d.chunks}</td>
                <td className="actions">
                  <button className="link" onClick={() => setDoc({ id: d.id, title: d.title, doc_type: d.doc_type, product_id: d.product_id ?? "", content: d.content })}>Edit</button>
                  <button className="link" onClick={async () => { await action.run("delete", () => api.del(`/knowledge/${d.id}`)); docs.reload(); }}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <h3>{doc.id ? "Edit document" : "Add document"}</h3>
        <form className="form-grid" onSubmit={saveDoc}>
          <label>Title<input required value={doc.title} onChange={(e) => setDoc({ ...doc, title: e.target.value })} /></label>
          <label>Type
            <select value={doc.doc_type} onChange={(e) => setDoc({ ...doc, doc_type: e.target.value })}>
              {["manual", "faq", "warranty_policy", "service", "policy"].map((t) => <option key={t} value={t}>{t.replace("_", " ")}</option>)}
            </select>
          </label>
          <label>Product
            <select value={doc.product_id} onChange={(e) => setDoc({ ...doc, product_id: e.target.value })}>
              <option value="">All products (general)</option>
              {products.data?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
          </label>
          <label className="span-2">Content (use “# Heading” lines to create sections)
            <textarea rows={8} required value={doc.content} onChange={(e) => setDoc({ ...doc, content: e.target.value })} />
          </label>
          <div className="span-2 actions"><button className="primary">{doc.id ? "Save changes" : "Add document"}</button>
            {doc.id && <button type="button" className="link" onClick={() => setDoc({ id: "", title: "", doc_type: "manual", product_id: "", content: "" })}>Cancel</button>}</div>
        </form>
      </Card>
    </>
  );
}
