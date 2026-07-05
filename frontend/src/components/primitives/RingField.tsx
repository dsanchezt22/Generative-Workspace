"use client";

import type { Ring } from "@/lib/types";
import { useLiveValue } from "@/lib/useLiveValue";
import { formatLiveNumber } from "@/lib/liveFormat";
import { LiveMeta } from "./LiveMeta";

interface Props {
  spec: Ring;
  value: number;
  onChange?: (v: number | "") => void; // omitted when bound to another field
}

export function RingField({ spec, value, onChange }: Props) {
  // R-701/R-703: a data_source drives the ring's fill from a live value
  // instead of the manual/bound one. The manual input (when present) always
  // stays bound to the manual `value` — never the live one — so editing it
  // keeps working exactly as before once live becomes stale/unavailable/off
  // (R-703: a dead provider never breaks the module).
  const live = useLiveValue(spec.data_source);
  const showLive = Boolean(spec.data_source) && !live.disabled;
  const liveActive = showLive && live.value !== null;
  const max = spec.max || 100;
  const manualV = Number(value) || 0;
  const v = liveActive ? live.value! : manualV;
  const pct = Math.max(0, Math.min(1, v / max));
  const R = 26, C = 2 * Math.PI * R;

  return (
    <div className="flex items-center gap-3">
      <svg viewBox="0 0 64 64" className="w-16 h-16 shrink-0 -rotate-90">
        <circle cx="32" cy="32" r={R} fill="none" stroke="var(--surface-elevated)" strokeWidth="7" />
        <circle cx="32" cy="32" r={R} fill="none" stroke="var(--accent)" strokeWidth="7" strokeLinecap="round"
          strokeDasharray={C} strokeDashoffset={C * (1 - pct)} style={{ transition: "stroke-dashoffset 0.3s ease" }} />
      </svg>
      <div className="flex flex-col gap-0.5 min-w-0">
        <span className="text-xs uppercase tracking-wide text-[var(--muted)] truncate">{spec.label}</span>
        <span className="text-lg font-semibold tabular-nums leading-none">{Math.round(pct * 100)}%</span>
        {onChange ? (
          <input
            type="number"
            value={value === undefined || value === null || (value as unknown) === "" ? "" : manualV}
            onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
            className="w-20 mt-1 rounded border border-[var(--border)] bg-[var(--surface-elevated)] px-1.5 py-0.5 text-xs focus:outline-none"
            placeholder={`/ ${max}`}
          />
        ) : (
          <span className="text-[10px] text-[var(--muted)] tabular-nums">{formatLiveNumber(v)} / {max}</span>
        )}
        {showLive && <LiveMeta live={live} />}
      </div>
    </div>
  );
}
