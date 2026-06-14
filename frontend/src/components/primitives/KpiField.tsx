"use client";

import type { Kpi } from "@/lib/types";

interface Props {
  spec: Kpi;
  value: number | "";
  onChange: (v: number | "") => void;
}

export function KpiField({ spec, value, onChange }: Props) {
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
    </div>
  );
}
