"use client";

import type { Gauge } from "@/lib/types";

interface Props {
  spec: Gauge;
  value: number;
  onChange?: (v: number | "") => void;
}

// 180° gauge (semicircle).
export function GaugeField({ spec, value, onChange }: Props) {
  const min = spec.min ?? 0;
  const max = spec.max ?? 100;
  const v = Number(value);
  const pct = Math.max(0, Math.min(1, ((Number.isFinite(v) ? v : min) - min) / (max - min || 1)));
  const R = 46;
  const C = Math.PI * R; // half circumference
  const cx = 60, cy = 56;

  return (
    <div className="flex flex-col items-center gap-1">
      <span className="text-xs uppercase tracking-wide text-[var(--muted)] self-start">{spec.label}</span>
      <svg viewBox="0 0 120 64" className="w-full max-w-[180px]">
        <path d={`M ${cx - R} ${cy} A ${R} ${R} 0 0 1 ${cx + R} ${cy}`} fill="none" stroke="var(--surface-elevated)" strokeWidth="9" strokeLinecap="round" />
        <path
          d={`M ${cx - R} ${cy} A ${R} ${R} 0 0 1 ${cx + R} ${cy}`}
          fill="none" stroke="var(--accent)" strokeWidth="9" strokeLinecap="round"
          strokeDasharray={C} strokeDashoffset={C * (1 - pct)} style={{ transition: "stroke-dashoffset 0.3s ease" }}
        />
        <text x={cx} y={cy - 6} textAnchor="middle" className="fill-[var(--foreground)]" style={{ fontSize: 16, fontWeight: 600 }}>
          {Number.isFinite(v) ? v : "—"}
        </text>
      </svg>
      <div className="flex items-center justify-between w-full text-[10px] text-[var(--muted)] -mt-1">
        <span>{min}</span>
        {spec.unit && <span>{spec.unit}</span>}
        <span>{max}</span>
      </div>
      {onChange && (
        <input
          type="range" min={min} max={max} value={Number.isFinite(v) ? v : min}
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-full accent-[var(--accent)]"
          aria-label={spec.label}
        />
      )}
    </div>
  );
}
