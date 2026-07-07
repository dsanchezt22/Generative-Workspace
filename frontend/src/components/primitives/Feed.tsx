"use client";

import type { Feed, FeedEntry } from "@/lib/types";

interface Props {
  spec: Feed;
  value: FeedEntry[];
}

// Closed badge set → a muted status-dim pill. draft = sage ("ready for you"),
// simulated = amber (the SEAM "not real" caution), failed = terracotta. No neon,
// all in-palette (DESIGN-ETHOS §2.5). An unknown/empty badge renders nothing.
const BADGE: Record<string, { bg: string; fg: string }> = {
  draft: { bg: "var(--status-ok-dim)", fg: "var(--status-ok)" },
  simulated: { bg: "var(--status-hold-dim)", fg: "var(--status-hold)" },
  failed: { bg: "var(--status-err-dim)", fg: "var(--status-err)" },
};

// The one new trusted component (SURF-2): a read-only feed an automation appends
// to. Title/body render as plain React text nodes ONLY (no raw-HTML injection
// path) even though the body may have transited an LLM. Newest first, Geist Mono
// timestamps, bounded by `max_items`.
export function FeedField({ spec, value }: Props) {
  const cap = spec.max_items ?? 20;
  const entries = (Array.isArray(value) ? value : []).slice().reverse().slice(0, cap);

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs uppercase tracking-wide text-[var(--muted)]">{spec.label}</span>
      {entries.length === 0 ? (
        <p className="text-xs text-[var(--muted)] leading-relaxed py-1">
          Nothing yet — the agent hasn&apos;t run.
        </p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {entries.map((e, i) => {
            const badge = BADGE[e.badge];
            return (
              <li
                key={i}
                className="rounded-md border border-[var(--border)] bg-[var(--surface-elevated)] px-3 py-2 flex flex-col gap-1"
              >
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-[var(--foreground)] flex-1 min-w-0 break-words">
                    {e.title}
                  </span>
                  {badge && (
                    <span
                      className="shrink-0 font-mono text-[9px] uppercase tracking-wide rounded px-1.5 py-0.5"
                      style={{ background: badge.bg, color: badge.fg }}
                    >
                      {e.badge}
                    </span>
                  )}
                </div>
                {e.body && (
                  <p className="text-xs text-[var(--muted)] leading-relaxed break-words">{e.body}</p>
                )}
                {e.ts && (
                  <span className="font-mono text-[10px] text-[var(--muted)]">
                    {new Date(e.ts).toLocaleString([], {
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
