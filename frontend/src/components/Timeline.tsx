import type { TimelineEvent } from "../types";

const ACTOR = { agent: "AI agent", human: "Human", system: "Backend rule", contact: "Contact" };

export function Timeline({ events }: { events: TimelineEvent[] }) {
  return (
    <ol className="vtimeline">
      {events.map((t, i) => (
        <li key={i} className={`actor-${t.actor ?? "system"}`}>
          <span className="vt-dot" aria-hidden />
          <div>
            <div>{t.description}</div>
            <div className="muted small">
              {ACTOR[t.actor ?? "system"]} · {new Date(t.at).toLocaleString()}
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}
