"use client";

import type { Heatmap } from "@/lib/types";

interface Props {
  spec: Heatmap;
  value: Record<string, number>;
  onChange: (v: Record<string, number>) => void;
}

const WEEKS = 18;
const pad = (n: number) => String(n).padStart(2, "0");
const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

export function HeatmapField({ spec, value, onChange }: Props) {
  const data = value && typeof value === "object" ? value : {};
  const today = new Date();
  // Build columns of 7 days ending today (most recent week on the right).
  const start = new Date(today);
  start.setDate(today.getDate() - (WEEKS * 7 - 1));

  const weeks: Date[][] = [];
  const cur = new Date(start);
  for (let w = 0; w < WEEKS; w++) {
    const col: Date[] = [];
    for (let d = 0; d < 7; d++) { col.push(new Date(cur)); cur.setDate(cur.getDate() + 1); }
    weeks.push(col);
  }

  const levelColor = (lvl: number) =>
    lvl <= 0 ? "var(--surface-elevated)" : `color-mix(in srgb, var(--accent) ${20 + lvl * 20}%, var(--surface-elevated))`;

  const cycle = (key: string) => {
    const next = ((data[key] || 0) + 1) % 5;
    const copy = { ...data };
    if (next === 0) delete copy[key]; else copy[key] = next;
    onChange(copy);
  };

  const total = Object.values(data).filter((v) => v > 0).length;

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between">
        <span className="text-xs uppercase tracking-wide text-[var(--muted)]">{spec.label}</span>
        <span className="text-[10px] text-[var(--muted)]">{total} day{total === 1 ? "" : "s"}{spec.unit ? ` · ${spec.unit}` : ""}</span>
      </div>
      <div className="flex gap-[3px] overflow-x-auto no-scrollbar">
        {weeks.map((col, wi) => (
          <div key={wi} className="flex flex-col gap-[3px]">
            {col.map((d) => {
              const key = iso(d);
              const future = d > today;
              return (
                <button
                  key={key}
                  type="button"
                  disabled={future}
                  onClick={() => cycle(key)}
                  className="w-3 h-3 rounded-[3px] transition hover:scale-110 disabled:opacity-30"
                  style={{ background: levelColor(data[key] || 0) }}
                  title={key}
                  aria-label={key}
                />
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
