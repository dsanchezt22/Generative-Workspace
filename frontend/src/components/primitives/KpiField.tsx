"use client";

import type { Kpi } from "@/lib/types";
import { useLiveValue } from "@/lib/useLiveValue";
import { formatLiveNumber } from "@/lib/liveFormat";
import { LiveMeta } from "./LiveMeta";

interface Props {
  spec: Kpi;
  value: number | "";
  onChange: (v: number | "") => void;
}

export function KpiField({ spec, value, onChange }: Props) {
  // R-701/R-703: a data_source augments the manual entry with a live readout
  // below it — the input itself is never touched, so the field stays
  // manually editable no matter what the live fetch does. `disabled`
  // (TRUS_LIVE_DATA=off) shows no live chrome at all.
  const live = useLiveValue(spec.data_source);
  const showLive = Boolean(spec.data_source) && !live.disabled;

  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs uppercase tracking-wide text-[var(--muted)]">{spec.label}</span>
      <div className="flex items-baseline gap-1">
        <input
          type="number"
          value={value === undefined || value === null ? "" : value}
          onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
          placeholder="0"
          className="w-full bg-transparent text-3xl font-semibold tabular-nums leading-none focus:outline-none placeholder:text-[var(--border)]"
          style={{ color: "var(--accent)" }}
        />
        {spec.unit && <span className="text-sm text-[var(--muted)] shrink-0">{spec.unit}</span>}
      </div>
      {showLive && (
        <div className="flex flex-col gap-0.5">
          {live.loading ? (
            <span className="h-3 w-24 rounded shimmer bg-[var(--surface-elevated)] inline-block" />
          ) : live.value !== null ? (
            <span className="text-xs text-[var(--muted)]">
              live{" "}
              <span className="font-mono tabular-nums text-[var(--foreground)]">
                {formatLiveNumber(live.value)}
              </span>
              {live.unit ? ` ${live.unit}` : ""}
            </span>
          ) : null}
          <LiveMeta live={live} />
        </div>
      )}
    </div>
  );
}
