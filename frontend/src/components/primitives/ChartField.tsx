"use client";

import { useState } from "react";
import type { ChartField as ChartSpec } from "@/lib/types";

interface Point { label: string; value: number }
interface Props {
  spec: ChartSpec;
  value: Point[];
  onChange: (v: Point[]) => void;
}

const W = 280, H = 120, PAD = 6;

export function ChartField({ spec, value, onChange }: Props) {
  const data = Array.isArray(value) ? value : [];
  const [label, setLabel] = useState("");
  const [val, setVal] = useState("");
  const type = spec.chart_type ?? "bar";
  const max = Math.max(1, ...data.map((d) => Number(d.value) || 0));

  const add = () => {
    const l = label.trim();
    const v = Number(val);
    if (!l || Number.isNaN(v)) return;
    onChange([...data, { label: l, value: v }]);
    setLabel(""); setVal("");
  };
  const removeAt = (i: number) => onChange(data.filter((_, idx) => idx !== i));

  const acc = "var(--accent)";

  const renderChart = () => {
    if (data.length === 0) return <p className="text-xs text-[var(--muted)] italic py-4 text-center">No data yet — add points below.</p>;
    const innerW = W - PAD * 2, innerH = H - PAD * 2;
    if (type === "pie") {
      const total = data.reduce((s, d) => s + (Number(d.value) || 0), 0) || 1;
      let angle = -Math.PI / 2;
      const cx = W / 2, cy = H / 2, r = Math.min(W, H) / 2 - PAD;
      return (
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-[120px]">
          {data.map((d, i) => {
            const frac = (Number(d.value) || 0) / total;
            const a2 = angle + frac * Math.PI * 2;
            const x1 = cx + r * Math.cos(angle), y1 = cy + r * Math.sin(angle);
            const x2 = cx + r * Math.cos(a2), y2 = cy + r * Math.sin(a2);
            const large = frac > 0.5 ? 1 : 0;
            const path = `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z`;
            angle = a2;
            return <path key={i} d={path} fill={`color-mix(in srgb, ${acc} ${100 - i * 12}%, var(--surface))`} stroke="var(--surface)" strokeWidth="1" />;
          })}
        </svg>
      );
    }
    const n = data.length;
    const x = (i: number) => PAD + (n === 1 ? innerW / 2 : (i / (n - 1)) * innerW);
    const y = (v: number) => PAD + innerH - ((Number(v) || 0) / max) * innerH;
    if (type === "bar") {
      const bw = innerW / n * 0.7;
      return (
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-[120px]">
          {data.map((d, i) => {
            const bx = PAD + (i + 0.15) * (innerW / n);
            const by = y(d.value);
            return <rect key={i} x={bx} y={by} width={bw} height={PAD + innerH - by} rx="2" fill={acc} />;
          })}
        </svg>
      );
    }
    const pts = data.map((d, i) => `${x(i)},${y(d.value)}`).join(" ");
    return (
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-[120px]">
        {type === "area" && (
          <polygon points={`${PAD},${PAD + innerH} ${pts} ${PAD + innerW},${PAD + innerH}`}
            fill={`color-mix(in srgb, ${acc} 25%, transparent)`} />
        )}
        <polyline points={pts} fill="none" stroke={acc} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {data.map((d, i) => <circle key={i} cx={x(i)} cy={y(d.value)} r="2.5" fill={acc} />)}
      </svg>
    );
  };

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs uppercase tracking-wide text-[var(--muted)]">{spec.label}</span>
      <div className="rounded-md bg-[var(--surface-elevated)] p-2">{renderChart()}</div>
      <div className="flex flex-col gap-1">
        {data.map((d, i) => (
          <div key={i} className="flex items-center gap-2 text-xs">
            <span className="w-2 h-2 rounded-sm shrink-0" style={{ background: acc }} />
            <span className="flex-1 truncate">{d.label}</span>
            <span className="tabular-nums text-[var(--muted)]">{d.value}{spec.unit ? ` ${spec.unit}` : ""}</span>
            <button type="button" onClick={() => removeAt(i)} className="text-[var(--muted)] hover:text-[var(--danger)]" aria-label="Remove point">×</button>
          </div>
        ))}
      </div>
      <div className="flex gap-1.5">
        <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Label"
          className="flex-1 min-w-0 rounded-md border border-[var(--border)] bg-[var(--surface-elevated)] px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40" />
        <input value={val} onChange={(e) => setVal(e.target.value)} type="number" placeholder="0"
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
          className="w-16 rounded-md border border-[var(--border)] bg-[var(--surface-elevated)] px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40" />
        <button type="button" onClick={add}
          className="rounded-md bg-[var(--accent)] text-[var(--accent-fg)] px-2 py-1 text-xs font-medium hover:brightness-110 transition">Add</button>
      </div>
    </div>
  );
}
