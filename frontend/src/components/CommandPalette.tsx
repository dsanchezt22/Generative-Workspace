"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { Page, StoredModule } from "@/lib/types";
import { resolveIconName } from "@/lib/theme";
import { Icon } from "./Icon";

export interface Action {
  id: string;
  label: string;
  hint?: string;
  run: () => void;
}

interface Props {
  open: boolean;
  onClose: () => void;
  pages: Page[];
  allModules: StoredModule[];
  actions: Action[];
  onGoToPage: (id: string) => void;
  onGoToModule: (m: StoredModule) => void;
}

interface Row {
  group: string;
  icon: ReactNode;
  label: string;
  sub?: string;
  run: () => void;
}

export function CommandPalette({ open, onClose, pages, allModules, actions, onGoToPage, onGoToModule }: Props) {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (open) {
      setQ("");
      setSel(0);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  const rows = useMemo<Row[]>(() => {
    const query = q.trim().toLowerCase();
    const out: Row[] = [];

    for (const a of actions) {
      if (!query || a.label.toLowerCase().includes(query)) {
        out.push({ group: "Commands", icon: <Icon name="sliders" size={15} />, label: a.label, sub: a.hint, run: a.run });
      }
    }
    if (query) {
      for (const p of pages) {
        if (p.name.toLowerCase().includes(query)) {
          out.push({ group: "Pages", icon: <Icon name={resolveIconName(p.icon, p.name)} size={15} />, label: p.name, run: () => onGoToPage(p.id) });
        }
      }
      for (const m of allModules) {
        const labels = m.config.components.map((c) => c.label).join(" ").toLowerCase();
        if (m.config.title.toLowerCase().includes(query) || labels.includes(query)) {
          out.push({ group: "Tools", icon: <Icon name={resolveIconName(m.config.icon, m.config.title)} size={15} />, label: m.config.title, run: () => onGoToModule(m) });
        }
      }
      for (const m of allModules) {
        for (const [, v] of Object.entries(m.config.state ?? {})) {
          const text = Array.isArray(v) ? v.join(", ") : typeof v === "string" ? v : "";
          if (text && text.toLowerCase().includes(query)) {
            out.push({ group: "Entries", icon: <Icon name="pen" size={15} />, label: text.slice(0, 50), sub: `in ${m.config.title}`, run: () => onGoToModule(m) });
            break;
          }
        }
      }
    }
    return out.slice(0, 40);
  }, [q, actions, pages, allModules, onGoToPage, onGoToModule]);

  useEffect(() => { setSel((s) => Math.min(s, Math.max(0, rows.length - 1))); }, [rows.length]);

  if (!open) return null;

  const choose = (r: Row) => { r.run(); onClose(); };

  let lastGroup = "";

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[12vh] bg-black/30 animate-fade" onMouseDown={onClose}>
      <div
        className="w-[min(560px,calc(100%-2rem))] rounded-lg border border-[var(--border)] bg-[var(--surface)] shadow-2xl shadow-black/40 overflow-hidden animate-scale-in"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <input
          ref={inputRef}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, rows.length - 1)); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
            else if (e.key === "Enter") { e.preventDefault(); if (rows[sel]) choose(rows[sel]); }
            else if (e.key === "Escape") { e.preventDefault(); onClose(); }
          }}
          placeholder="Search tools, pages, entries, or type a command…"
          className="w-full bg-transparent px-4 py-3.5 text-sm focus:outline-none border-b border-[var(--border)] placeholder:text-[var(--muted)]"
        />
        <div className="max-h-[50vh] overflow-y-auto py-1">
          {rows.length === 0 && (
            <div className="px-4 py-6 text-sm text-[var(--muted)] text-center">
              Nothing found.{q.trim() && " Try the creation bar to make it."}
            </div>
          )}
          {rows.map((r, i) => {
            const header = r.group !== lastGroup ? r.group : null;
            lastGroup = r.group;
            return (
              <div key={i}>
                {header && <div className="px-4 pt-2 pb-1 text-[10px] uppercase tracking-wide text-[var(--muted)]">{header}</div>}
                <button
                  type="button"
                  onMouseEnter={() => setSel(i)}
                  onClick={() => choose(r)}
                  className={`w-full flex items-center gap-2.5 px-4 py-2 text-left text-sm transition ${i === sel ? "bg-[var(--surface-elevated)]" : ""}`}
                >
                  <span className="shrink-0 w-5 grid place-items-center text-[var(--muted)]">{r.icon}</span>
                  <span className="flex-1 truncate">{r.label}</span>
                  {r.sub && <span className="text-xs text-[var(--muted)] truncate shrink-0 max-w-[40%]">{r.sub}</span>}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
