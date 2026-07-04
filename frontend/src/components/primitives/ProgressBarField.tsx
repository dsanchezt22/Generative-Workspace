"use client";

import type { ProgressBar } from "@/lib/types";
import { useLiveValue } from "@/lib/useLiveValue";
import { LiveMeta } from "./LiveMeta";

interface Props {
  spec: ProgressBar;
  value: number;
}

export function ProgressBarField({ spec, value }: Props) {
  // R-701/R-703: a data_source drives the fill from a live value instead of
  // the bound/manual one. `disabled` (TRUS_LIVE_DATA=off) falls all the way
  // back to the original bound-value display — no live chrome at all.
  const live = useLiveValue(spec.data_source);
  const showLive = Boolean(spec.data_source) && !live.disabled;
  const liveActive = showLive && live.value !== null;
  const max = spec.max || 1;
  const pct = Math.max(0, Math.min(1, (liveActive ? live.value! : Number(value) || 0) / max));

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between text-xs uppercase tracking-wide text-[var(--muted)]">
        <span>{spec.label}</span>
        <span className="font-mono text-[var(--foreground)] normal-case tracking-normal">
          {showLive && live.loading ? "…" : `${Math.round(pct * 100)}%`}
        </span>
      </div>
      <div className="h-2 rounded-full bg-[var(--surface-elevated)] overflow-hidden">
        {showLive && live.loading ? (
          <div className="h-full w-1/3 rounded-full shimmer bg-[var(--surface-elevated)]" />
        ) : (
          <div
            className="h-full rounded-full bg-[var(--accent)] transition-[width] duration-300 ease-out"
            style={{ width: `${pct * 100}%` }}
          />
        )}
      </div>
      {showLive && <LiveMeta live={live} />}
    </div>
  );
}
