"use client";

import { useState } from "react";
import type { Tracker } from "@/lib/types";

interface Row { name: string; done: string[] }
interface Props {
  spec: Tracker;
  value: { rows: Row[] };
  onChange: (v: { rows: Row[] }) => void;
}

const pad = (n: number) => String(n).padStart(2, "0");

function dayKey(d: Date) { return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; }
function weekKey(d: Date) {
  const date = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const dayNum = (date.getUTCDay() + 6) % 7;
  date.setUTCDate(date.getUTCDate() - dayNum + 3);
  const firstThu = new Date(Date.UTC(date.getUTCFullYear(), 0, 4));
  const week = 1 + Math.round((date.getTime() - firstThu.getTime()) / 604800000);
  return `${date.getUTCFullYear()}-W${pad(week)}`;
}

export function TrackerField({ spec, value, onChange }: Props) {
  const period = spec.period ?? "day";
  const rows: Row[] = value && Array.isArray(value.rows) ? value.rows : [];
  const [draft, setDraft] = useState("");

  const keyOf = (d: Date) => (period === "week" ? weekKey(d) : dayKey(d));
  const prev = (d: Date) => { const n = new Date(d); n.setDate(n.getDate() - (period === "week" ? 7 : 1)); return n; };
  const today = new Date();
  const todayKey = keyOf(today);

  const setRows = (next: Row[]) => onChange({ rows: next });
  const toggle = (i: number) => {
    const r = rows[i];
    const has = r.done.includes(todayKey);
    const done = has ? r.done.filter((k) => k !== todayKey) : [...r.done, todayKey];
    setRows(rows.map((x, idx) => (idx === i ? { ...x, done } : x)));
  };
  const rename = (i: number, name: string) => setRows(rows.map((x, idx) => (idx === i ? { ...x, name } : x)));
  const remove = (i: number) => setRows(rows.filter((_, idx) => idx !== i));
  const add = () => { const n = draft.trim(); if (!n) return; setRows([...rows, { name: n, done: [] }]); setDraft(""); };

  const streak = (done: string[]) => {
    const set = new Set(done);
    let s = 0; let d = new Date(today);
    if (!set.has(keyOf(d))) d = prev(d); // grace: current period not done yet doesn't break it
    while (set.has(keyOf(d))) { s++; d = prev(d); }
    return s;
  };
  const completion = (done: string[]) => {
    const set = new Set(done);
    const N = period === "week" ? 12 : 30;
    let c = 0; let d = new Date(today);
    for (let i = 0; i < N; i++) { if (set.has(keyOf(d))) c++; d = prev(d); }
    return Math.round((c / N) * 100);
  };
  const lastDots = (done: string[]) => {
    const set = new Set(done);
    const out: boolean[] = [];
    let d = new Date(today);
    for (let i = 0; i < 7; i++) { out.unshift(set.has(keyOf(d))); d = prev(d); }
    return out;
  };

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between">
        <span className="text-xs uppercase tracking-wide text-[var(--muted)]">{spec.label}</span>
        <span className="text-[10px] text-[var(--muted)]">resets each {period}</span>
      </div>
      <div className="flex flex-col divide-y divide-[var(--border)] rounded-none border border-[var(--border)] overflow-hidden">
        {rows.map((r, i) => {
          const doneNow = r.done.includes(todayKey);
          const st = streak(r.done);
          const pct = spec.goal ? Math.min(100, Math.round((st / spec.goal) * 100)) : completion(r.done);
          return (
            <div key={i} className="group flex items-center gap-2 px-2 py-1.5 bg-[var(--surface)]">
              <button
                type="button"
                onClick={() => toggle(i)}
                className="w-5 h-5 rounded-full border grid place-items-center shrink-0 transition"
                style={{ borderColor: doneNow ? "var(--accent)" : "var(--border)", background: doneNow ? "var(--accent)" : "transparent", color: "var(--accent-fg)" }}
                aria-label={`Mark ${r.name} done`}
                title={doneNow ? "Done — tap to undo" : "Mark done"}
              >
                {doneNow && <span className="text-[11px] leading-none">✓</span>}
              </button>
              <input
                value={r.name}
                onChange={(e) => rename(i, e.target.value)}
                className="flex-1 min-w-0 bg-transparent text-sm focus:outline-none"
                aria-label="Subject name"
              />
              <div className="hidden sm:flex items-center gap-[2px] shrink-0">
                {lastDots(r.done).map((on, di) => (
                  <span key={di} className="w-1.5 h-1.5 rounded-full" style={{ background: on ? "var(--accent)" : "var(--surface-elevated)" }} />
                ))}
              </div>
              <span className="text-xs tabular-nums shrink-0 w-10 text-right" style={{ color: st > 0 ? "var(--accent)" : "var(--muted)" }} title="Streak">🔥{st}</span>
              <span className="text-[10px] tabular-nums text-[var(--muted)] shrink-0 w-9 text-right" title={spec.goal ? `toward ${spec.goal}` : "last 30"}>{pct}%</span>
              <button type="button" onClick={() => remove(i)} className="text-[var(--muted)] hover:text-[var(--danger)] text-xs opacity-0 group-hover:opacity-100 shrink-0" aria-label="Remove">×</button>
            </div>
          );
        })}
        {rows.length === 0 && <div className="px-2 py-2 text-xs text-[var(--muted)] italic bg-[var(--surface)]">No subjects yet.</div>}
      </div>
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
        placeholder={`Add a ${period === "week" ? "weekly " : ""}subject…`}
        className="rounded-sm border border-[var(--border)] bg-[var(--surface-elevated)] px-2.5 py-1.5 text-sm placeholder:text-[var(--muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40"
      />
    </div>
  );
}
