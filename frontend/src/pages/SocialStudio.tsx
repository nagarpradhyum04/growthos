import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, fetchObjectUrl } from "../api";
import { MediaPreview } from "../components/trace";
import { Badge, Card, Empty, ErrorBanner, Notice } from "../components/ui";
import { useAction, useAsync } from "../components/useAsync";
import type { SocialOverview, SocialPost, WorkflowSummary } from "../types";

const WAITING = ["COMPLETED", "BLOCKED", "FAILED", "AWAITING_APPROVAL", "ESCALATED"];
const STATUS_HELP: Record<string, string> = {
  READY: "Ready for your approval",
  NEEDS_REVIEW: "Flagged by your rules — fix before approving",
  FAILED: "Media generation failed",
  GENERATING: "Being generated…",
  APPROVED: "Approved — ready to publish on your page",
  REJECTED: "Rejected",
};

function fmtWeek(iso: string) {
  const d = new Date(`${iso}T00:00:00`);
  return `Week of ${d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}`;
}

export default function SocialStudio() {
  const overview = useAsync(() => api.get<SocialOverview>("/social/overview"));
  const posts = useAsync(() => api.get<SocialPost[]>("/social/posts?weeks=12"));
  const [week, setWeek] = useState<string | null>(null);
  const [running, setRunning] = useState<WorkflowSummary | null>(null);
  const action = useAction();

  const weeks = useMemo(() => {
    const set = new Set((posts.data ?? []).map((p) => p.week_start));
    if (overview.data) set.add(overview.data.current_week);
    return [...set].sort().reverse();
  }, [posts.data, overview.data]);
  const selected = week ?? overview.data?.current_week ?? weeks[0] ?? null;
  const weekPosts = (posts.data ?? []).filter((p) => p.week_start === selected).sort((a, b) => a.kind.localeCompare(b.kind));
  const isCurrent = selected === overview.data?.current_week;

  // Follow the Orchestrator run until it hands the posts to a human (or fails).
  useEffect(() => {
    if (!running || WAITING.includes(running.state)) return;
    const t = window.setTimeout(async () => {
      const fresh = await api.get<WorkflowSummary>(`/workflows/${running.id}`).catch(() => running);
      setRunning(fresh);
      posts.reload();
    }, 1500);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);

  async function generate(regenerate: boolean) {
    const res = await action.run("generate", () => api.post<{ workflow_id: string }>("/social/generate", { week_start: selected, regenerate }));
    if (res) setRunning(await api.get<WorkflowSummary>(`/workflows/${res.workflow_id}`));
  }

  const ov = overview.data;
  const live = running && !WAITING.includes(running.state);
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Social Studio</h1>
          <p className="muted page-sub">Every week the Social Content Agent plans one promotional theme for your page and writes a <b>static image post</b> and a <b>short video post</b> from your business profile and product catalogue. Nothing is ever posted automatically — you approve each one.</p>
        </div>
      </div>
      <ErrorBanner error={overview.error ?? posts.error ?? action.error} onClose={() => action.setError(null)} />
      <Notice message={action.notice} />

      {ov && (
        <Card>
          <div className="row-head" style={{ flexWrap: "wrap" }}>
            <div className="stack" style={{ gap: 4 }}>
              <span className="provider-line">Image: {ov.media_provider === "gemini" ? `${ov.image_model} (Nano Banana)` : "mock preview"} · Video: {ov.media_provider === "gemini" ? `${ov.video_model} (Veo)` : "mock storyboard"}</span>
              <span className="provider-line">Weekly auto-draft: {ov.weekly_enabled ? "on" : "off"} · Platforms: {ov.platforms.join(", ") || "none"} · <Link to="/settings">change in Settings &amp; Rules</Link></span>
            </div>
            <div className="week-nav">
              <select value={selected ?? ""} onChange={(e) => setWeek(e.target.value)} aria-label="Week">
                {weeks.map((w) => <option key={w} value={w}>{fmtWeek(w)}{w === ov.current_week ? " (this week)" : ""}</option>)}
              </select>
              {weekPosts.length === 0 ? (
                <button className="primary" disabled={!!action.busy || !!live} onClick={() => generate(false)}>
                  {isCurrent ? "Generate this week's posts" : "Generate posts for this week"}</button>
              ) : (
                <button disabled={!!action.busy || !!live || weekPosts.every((p) => ["APPROVED", "REJECTED"].includes(p.status))}
                        onClick={() => generate(true)} title="Rewrites and re-renders posts that are not approved or rejected">Regenerate unapproved</button>
              )}
            </div>
          </div>
          {ov.media_provider !== "gemini" && (
            <p className="banner info small" style={{ marginTop: 12 }}><span>Media is in <b>mock mode</b>: previews are labelled placeholders built from the real captions. Set <code>MEDIA_PROVIDER=gemini</code> and <code>GEMINI_API_KEY</code> to generate real images with Nano Banana and videos with Veo.</span></p>
          )}
          {running && (
            <p className="small" style={{ marginBottom: 0 }}>
              <Badge value={running.state === "AWAITING_APPROVAL" ? "WAITING" : running.state} />{" "}
              {live ? "Agents are working on it…" : running.error ?? "Done."} <Link to={`/workflows/${running.id}`}>Agent trace →</Link>
            </p>
          )}
        </Card>
      )}

      {posts.data && weekPosts.length === 0 && !live && (
        <Card><Empty>No posts for {selected ? fmtWeek(selected).toLowerCase() : "this week"} yet. Generate them above, or type “Create this week's social media posts” in the Command Center.</Empty></Card>
      )}
      <div className="social-grid">
        {weekPosts.map((p) => <PostCard key={p.id} post={p} onChange={posts.reload} />)}
      </div>
    </>
  );
}

function PostCard({ post, onChange }: { post: SocialPost; onChange: () => void }) {
  const [caption, setCaption] = useState(post.caption);
  const [tags, setTags] = useState(post.hashtags.join(" "));
  const [headline, setHeadline] = useState(post.headline);
  const action = useAction();
  useEffect(() => { setCaption(post.caption); setTags(post.hashtags.join(" ")); setHeadline(post.headline); }, [post]);

  const final = post.status === "APPROVED" || post.status === "REJECTED";
  const dirty = caption !== post.caption || tags !== post.hashtags.join(" ") || headline !== post.headline;
  const busy = !!action.busy;

  async function save() {
    const hashtags = tags.split(/[\s,]+/).map((t) => t.trim()).filter(Boolean);
    if (await action.run("save", () => api.patch(`/social/posts/${post.id}`, { caption, hashtags, headline }), "Saved. Rules re-checked.")) onChange();
  }
  async function act(path: string, notice: string) {
    if (await action.run(path, () => api.post(`/social/posts/${post.id}/${path}`, {}), notice)) onChange();
  }
  async function download() {
    const url = await fetchObjectUrl(`/social/posts/${post.id}/media`);
    const a = document.createElement("a");
    const ext = (post.media_mime ?? "").split("/")[1]?.replace("svg+xml", "svg") ?? "bin";
    a.href = url;
    a.download = `${post.kind}-post-${post.week_start}.${ext}`;
    a.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return (
    <article className="social-card">
      <div className="social-media">
        {post.has_media ? <MediaPreview postId={post.id} mime={post.media_mime} version={post.updated_at} /> : (
          <div className="placeholder">{post.status === "GENERATING" ? "Generating…" : post.error ?? "No media yet"}</div>
        )}
        {post.has_media && <span className={`media-tag ${post.is_mock_media ? "mock" : ""}`}>{post.is_mock_media ? "Mock preview" : post.media_model}</span>}
      </div>
      <div className="social-body">
        <div className="row-head">
          <span className="social-kind">{post.kind === "image" ? "Static image post" : "Video post"} · {post.platforms.join(" / ")}</span>
          <Badge value={post.status} />
        </div>
        <h2 style={{ margin: 0 }}>{post.theme || "—"}</h2>
        <span className="muted small">{STATUS_HELP[post.status]}</span>
        {post.policy_notes.length > 0 && (
          <div className="policy-notes"><b>Safety Agent flagged:</b><ul>{post.policy_notes.map((n) => <li key={n}>{n}</li>)}</ul></div>
        )}
        {post.error && post.status === "FAILED" && <div className="banner error small"><span>{post.error}</span></div>}
        <ErrorBanner error={action.error} onClose={() => action.setError(null)} />
        <Notice message={action.notice} />
        {post.kind === "image" && (
          <label className="small">Headline on the image
            <input value={headline} disabled={final} maxLength={200} onChange={(e) => setHeadline(e.target.value)} />
          </label>
        )}
        <label className="small">Caption
          <textarea rows={5} value={caption} disabled={final} onChange={(e) => setCaption(e.target.value)} />
        </label>
        <label className="small">Hashtags
          <input value={tags} disabled={final} onChange={(e) => setTags(e.target.value)} />
        </label>
        <details>
          <summary className="small">{post.kind === "image" ? "Visual prompt sent to Nano Banana" : "Video prompt sent to Veo"}</summary>
          <pre className="doc">{post.media_prompt || "—"}</pre>
          {post.agent_run_id && <span className="muted small">Written by the Social Content Agent (run {post.agent_run_id.slice(0, 8)})</span>}
        </details>
        <div className="actions">
          {!final && <>
            <button className="primary" disabled={busy || dirty || !post.has_media || post.policy_notes.length > 0}
                    title={dirty ? "Save your edits first" : post.policy_notes.length ? "Fix the flagged items first" : "Approve for publishing. GrowthOS never posts automatically."}
                    onClick={() => act("approve", "Approved. Download it and publish it on your page.")}>Approve post</button>
            {dirty && <button disabled={busy} onClick={save}>Save edits</button>}
            <button disabled={busy || dirty} onClick={() => act("regenerate-media", post.kind === "video" ? "New video generated." : "New image generated.")}>
              {busy && action.busy === "regenerate-media" ? "Generating…" : post.kind === "image" ? "New image" : "New video"}</button>
            <button className="danger-outline" disabled={busy} onClick={() => act("reject", "Post rejected.")}>Reject</button>
          </>}
          {post.has_media && <button className="link" onClick={download}>Download {post.kind === "image" ? "image" : "video"}</button>}
          {post.status === "APPROVED" && <button className="link" onClick={() => navigator.clipboard?.writeText(`${post.caption}\n\n${post.hashtags.join(" ")}`)}>Copy caption</button>}
        </div>
      </div>
    </article>
  );
}
