"use client";

import { useState } from "react";
import type { Timeline } from "@/lib/types";

interface Event { date: string; label: string }
interface Props {
  spec: Timeline;
  value: Event[];
  onChange: (v: Event[]) => void;
}

export function TimelineField({ spec, value, onChange }: Props) {
  const events = Array.isArray(value) ? value : [];
  const [date, setDate] = useState("");
  const [label, setLabel] = useState("");

  const sorted = [...events].sort((a, b) => (a.date || "").localeCompare(b.date || ""));

  const add = () => {
    if (!label.trim()) return;
    onChange([...events, { date, label: label.trim() }]);
    setDate(""); setLabel("");
  };
  const removeAt = (i: number) => onChange(events.filter((e) => e !== sorted[i]));

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs uppercase tracking-wide text-[var(--muted)]">{spec.label}</span>
      <ol className="flex flex-col gap-0 ml-1 border-l-2 border-[var(--border)]">
        {sorted.map((e, i) => (
          <li key={i} className="relative pl-4 pb-2.5 group">
            <span className="absolute -left-[5px] top-1 w-2 h-2 rounded-full" style={{ background: "var(--accent)" }} />
            <div className="flex items-baseline gap-2">
              <span className="text-[10px] font-mono text-[var(--muted)] shrink-0">{e.date || "—"}</span>
              <span className="text-sm flex-1">{e.label}</span>
              <button type="button" onClick={() => removeAt(i)} className="text-[var(--muted)] hover:text-[var(--danger)] text-xs opacity-0 group-hover:opacity-100">×</button>
            </div>
          </li>
        ))}
        {sorted.length === 0 && <li className="pl-4 pb-2 text-xs text-[var(--muted)] italic">No events yet.</li>}
      </ol>
      <div className="flex gap-1.5">
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)}
          className="rounded-md border border-[var(--border)] bg-[var(--surface-elevated)] px-2 py-1 text-xs focus:outline-none" />
        <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Event"
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
          className="flex-1 min-w-0 rounded-md border border-[var(--border)] bg-[var(--surface-elevated)] px-2 py-1 text-xs focus:outline-none" />
        <button type="button" onClick={add} className="rounded-md bg-[var(--accent)] text-[var(--accent-fg)] px-2 py-1 text-xs font-medium hover:brightness-110 transition">Add</button>
      </div>
    </div>
  );
}
