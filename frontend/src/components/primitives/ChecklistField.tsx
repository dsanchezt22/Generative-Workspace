"use client";

import { useState } from "react";
import type { Checklist } from "@/lib/types";

interface Item { text: string; done: boolean }
interface Props {
  spec: Checklist;
  value: Item[];
  onChange: (v: Item[]) => void;
}

export function ChecklistField({ spec, value, onChange }: Props) {
  const items = Array.isArray(value) ? value : [];
  const [draft, setDraft] = useState("");
  const done = items.filter((i) => i.done).length;
  const pct = items.length ? Math.round((done / items.length) * 100) : 0;

  const add = () => {
    const t = draft.trim();
    if (!t) return;
    onChange([...items, { text: t, done: false }]);
    setDraft("");
  };
  const toggle = (i: number) => onChange(items.map((it, idx) => (idx === i ? { ...it, done: !it.done } : it)));
  const remove = (i: number) => onChange(items.filter((_, idx) => idx !== i));

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between">
        <span className="text-xs uppercase tracking-wide text-[var(--muted)]">{spec.label}</span>
        <span className="text-[10px] text-[var(--muted)]">{done}/{items.length}</span>
      </div>
      {items.length > 0 && (
        <div className="h-1.5 rounded-full bg-[var(--surface-elevated)] overflow-hidden">
          <div className="h-full rounded-full bg-[var(--accent)] transition-[width] duration-300" style={{ width: `${pct}%` }} />
        </div>
      )}
      <ul className="flex flex-col">
        {items.map((it, i) => (
          <li key={i} className="group flex items-center gap-2 py-1">
            <button
              type="button"
              onClick={() => toggle(i)}
              className="w-4 h-4 rounded border grid place-items-center shrink-0 transition"
              style={{ borderColor: it.done ? "var(--accent)" : "var(--border)", background: it.done ? "var(--accent)" : "transparent", color: "var(--accent-fg)" }}
              aria-label={it.done ? "Mark undone" : "Mark done"}
            >
              {it.done && <span className="text-[10px] leading-none">✓</span>}
            </button>
            <span className={`flex-1 text-sm ${it.done ? "line-through text-[var(--muted)]" : ""}`}>{it.text}</span>
            <button type="button" onClick={() => remove(i)} className="text-[var(--muted)] hover:text-[var(--danger)] text-xs opacity-0 group-hover:opacity-100" aria-label="Remove">×</button>
          </li>
        ))}
      </ul>
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
        placeholder="Add item…"
        className="rounded-md border border-[var(--border)] bg-[var(--surface-elevated)] px-2.5 py-1.5 text-sm placeholder:text-[var(--muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40"
      />
    </div>
  );
}
