"use client";

import type { LiveValueState } from "@/lib/useLiveValue";
import { formatRelativeTime } from "@/lib/liveFormat";

/**
 * Shared freshness/provenance/stale row for the 5 live-data-capable
 * primitives (R-701/R-703). Muted mono text, no new palette — matches
 * DESIGN-ETHOS.md §7.3's "machine register" for anything that represents
 * data/state, and §2.5's "desaturated, never neon" status styling.
 *
 * Renders nothing while the first fetch is in flight — the caller's own
 * skeleton/placeholder already communicates "loading" (R-1305: the value
 * stays the visual focus, this row never competes with it).
 */
export function LiveMeta({ live }: { live: LiveValueState }) {
  if (live.loading) return null;

  if (live.value === null) {
    // Error, and nothing was ever cached — a subtle "unavailable" note; the
    // component itself stays whatever it normally is (manual/computed).
    return (
      <span className="text-[9px] font-mono text-[var(--muted)]">
        via {live.source} — unavailable
      </span>
    );
  }

  const rel = formatRelativeTime(live.asOf);
  return (
    <div className="flex flex-wrap items-center gap-1 text-[9px] font-mono text-[var(--muted)]">
      <span>
        {rel ? `as of ${rel} · ` : ""}via {live.source}
      </span>
      {(live.stale || live.error) && (
        <span className="rounded px-1 py-px uppercase tracking-wide bg-[var(--surface-elevated)]">
          {live.error && !live.stale ? "couldn't update" : "stale"}
        </span>
      )}
    </div>
  );
}
