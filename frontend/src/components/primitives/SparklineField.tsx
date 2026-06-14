"use client";

import { useState } from "react";
import type { Sparkline } from "@/lib/types";

interface Props {
  spec: Sparkline;
  value: number[];
  onChange: (v: number[]) => void;
}

const W = 120, H = 28;

export function SparklineField({ spec, value, onChange }: Props) {
  const [draft, setDraft] = useState("");
  const data = Array.isArray(value) ? value.map(Number).filter((n) => !Number.isNaN(n)) : [];
  const max = Math.max(1, ...data);
  const min = Math.min(0, ...data);
  const range = max - min || 1;
  const pts = data.map((v, i) => {
    const x = data.length === 1 ? W / 2 : (i / (data.length - 1)) * W;
    const y = H - ((v - min) / range) * H;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");

  const add = () => {
    const n = Number(draft);
    if (Number.isNaN(n) || draft.trim() === "") return;
    onChange([...data, n]);
    setDraft("");
  };

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-[var(--muted)] shrink-0">{spec.label}</span>
      <svg viewBox={`0 0 ${W} ${H}`} className="flex-1 h-7" preserveAspectRatio="none">
        {data.length > 1 && <polyline points={pts} fill="none" stroke="var(--accent)" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />}
        {data.length === 1 && <circle cx={W / 2} cy={H / 2} r="2" fill="var(--accent)" />}
      </svg>
      <span className="text-xs tabular-nums text-[var(--foreground)] shrink-0">
        {data.length ? data[data.length - 1] : "—"}{spec.unit ? ` ${spec.unit}` : ""}
      </span>
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
        onBlur={add}
        type="number"
        placeholder="+"
        className="w-10 rounded border border-[var(--border)] bg-[var(--surface-elevated)] px-1 py-0.5 text-xs focus:outline-none shrink-0"
        aria-label={`Add ${spec.label} value`}
      />
    </div>
  );
}
