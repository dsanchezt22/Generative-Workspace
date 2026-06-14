"use client";

import { useState } from "react";
import type { CalendarField as CalendarSpec } from "@/lib/types";

interface Props {
  spec: CalendarSpec;
  value: string[];
  onChange: (v: string[]) => void;
}

const pad = (n: number) => String(n).padStart(2, "0");
const iso = (y: number, m: number, d: number) => `${y}-${pad(m + 1)}-${pad(d)}`;
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const DOW = ["S", "M", "T", "W", "T", "F", "S"];

export function CalendarField({ spec, value, onChange }: Props) {
  const marks = Array.isArray(value) ? value : [];
  const today = new Date();
  const [cursor, setCursor] = useState(() => new Date(today.getFullYear(), today.getMonth(), 1));
  const year = cursor.getFullYear();
  const month = cursor.getMonth();
  const todayIso = iso(today.getFullYear(), today.getMonth(), today.getDate());

  const firstDow = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells: (number | null)[] = [
    ...Array(firstDow).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];

  const toggle = (d: number) => {
    const key = iso(year, month, d);
    onChange(marks.includes(key) ? marks.filter((x) => x !== key) : [...marks, key]);
  };
  const shift = (delta: number) => setCursor(new Date(year, month + delta, 1));

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <span className="text-xs uppercase tracking-wide text-[var(--muted)]">{spec.label}</span>
        <div className="flex items-center gap-1 text-xs">
          <button type="button" onClick={() => shift(-1)} className="px-1 text-[var(--muted)] hover:text-[var(--foreground)]" aria-label="Previous month">‹</button>
          <span className="tabular-nums">{MONTHS[month].slice(0, 3)} {year}</span>
          <button type="button" onClick={() => shift(1)} className="px-1 text-[var(--muted)] hover:text-[var(--foreground)]" aria-label="Next month">›</button>
        </div>
      </div>
      <div className="grid grid-cols-7 gap-0.5">
        {DOW.map((d, i) => (
          <div key={i} className="text-center text-[10px] text-[var(--muted)] py-0.5">{d}</div>
        ))}
        {cells.map((d, i) => {
          if (d === null) return <div key={i} />;
          const key = iso(year, month, d);
          const marked = marks.includes(key);
          const isToday = key === todayIso;
          return (
            <button
              key={i}
              type="button"
              onClick={() => toggle(d)}
              className="aspect-square grid place-items-center rounded-md text-xs transition"
              style={{
                background: marked ? "var(--accent)" : "transparent",
                color: marked ? "var(--accent-fg)" : "var(--foreground)",
                outline: isToday && !marked ? "1px solid var(--accent)" : "none",
                outlineOffset: "-1px",
              }}
              aria-label={key}
            >
              {d}
            </button>
          );
        })}
      </div>
    </div>
  );
}
