"use client";

import type { Metric } from "@/lib/types";
import { useCountUp } from "@/lib/useCountUp";
import { useLiveValue } from "@/lib/useLiveValue";
import { formatLiveNumber } from "@/lib/liveFormat";
import { LiveMeta } from "./LiveMeta";

interface Props {
  spec: Metric;
  value: number;
}

const FORMULA_LABEL: Record<Metric["formula"], string> = {
  sum: "Total",
  count: "Count",
  avg: "Avg",
  max: "Max",
  min: "Min",
};

export function MetricField({ spec, value }: Props) {
  // R-701/R-703: a data_source overrides the formula-computed value with a
  // live one. `disabled` (TRUS_LIVE_DATA=off) falls all the way back to the
  // original formula display — no live chrome at all.
  const live = useLiveValue(spec.data_source);
  const showLive = Boolean(spec.data_source) && !live.disabled;
  const liveActive = showLive && live.value !== null;
  const displayValue = liveActive ? live.value! : value;
  const unit = liveActive ? live.unit : spec.unit;
  // Honesty (R-701): only claim "live" when there's an actual live value or one
  // is loading. If the provider is down with nothing cached (value === null &&
  // !loading), the number shown is the manual/computed formula value — so label
  // it as such and let LiveMeta's "via X — unavailable" carry the provenance,
  // rather than badging a non-live value "live".
  const liveTag = showLive && (live.loading || live.value !== null);

  const animated = useCountUp(displayValue);

  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-baseline justify-between">
        <span className="text-xs text-[var(--muted)]">{spec.label}</span>
        <span className="text-[10px] text-[var(--muted)] font-mono uppercase tracking-wide">
          {liveTag ? "live" : FORMULA_LABEL[spec.formula]}
        </span>
      </div>
      <div className="flex items-baseline gap-1">
        {showLive && live.loading ? (
          <span className="h-6 w-16 rounded shimmer bg-[var(--surface-elevated)] inline-block" />
        ) : (
          <span className="text-2xl font-semibold tabular-nums leading-none">
            {formatLiveNumber(displayValue, animated)}
          </span>
        )}
        {unit && <span className="text-xs text-[var(--muted)]">{unit}</span>}
      </div>
      {showLive && <LiveMeta live={live} />}
    </div>
  );
}
