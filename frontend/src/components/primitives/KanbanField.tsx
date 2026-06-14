"use client";

import { useState } from "react";
import type { Kanban } from "@/lib/types";

interface Props {
  spec: Kanban;
  value: Record<string, string[]>;
  onChange: (v: Record<string, string[]>) => void;
}

export function KanbanField({ spec, value, onChange }: Props) {
  const cols = spec.columns?.length ? spec.columns : ["To do", "Doing", "Done"];
  const board = value && typeof value === "object" && !Array.isArray(value) ? value : {};
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  const cards = (c: string) => (Array.isArray(board[c]) ? board[c] : []);
  const add = (c: string) => {
    const t = (drafts[c] || "").trim();
    if (!t) return;
    onChange({ ...board, [c]: [...cards(c), t] });
    setDrafts((d) => ({ ...d, [c]: "" }));
  };
  const remove = (c: string, i: number) => onChange({ ...board, [c]: cards(c).filter((_, idx) => idx !== i) });

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs uppercase tracking-wide text-[var(--muted)]">{spec.label}</span>
      <div className="flex gap-2 overflow-x-auto no-scrollbar pb-1">
        {cols.map((c) => (
          <div key={c} className="shrink-0 w-40 rounded-lg bg-[var(--surface-elevated)] p-1.5 flex flex-col gap-1.5">
            <div className="flex items-center justify-between px-1">
              <span className="text-[11px] font-medium uppercase tracking-wide text-[var(--muted)] truncate">{c}</span>
              <span className="text-[10px] text-[var(--muted)]">{cards(c).length}</span>
            </div>
            {cards(c).map((card, i) => (
              <div key={i} className="group rounded-md bg-[var(--surface)] border border-[var(--border)] px-2 py-1.5 text-xs flex items-start gap-1">
                <span className="flex-1 break-words">{card}</span>
                <button type="button" onClick={() => remove(c, i)} className="text-[var(--muted)] hover:text-[var(--danger)] opacity-0 group-hover:opacity-100" aria-label="Remove card">×</button>
              </div>
            ))}
            <input
              value={drafts[c] || ""}
              onChange={(e) => setDrafts((d) => ({ ...d, [c]: e.target.value }))}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(c); } }}
              onBlur={() => add(c)}
              placeholder="+ add"
              className="bg-transparent text-xs px-1 py-1 placeholder:text-[var(--muted)] focus:outline-none"
            />
          </div>
        ))}
      </div>
    </div>
  );
}
