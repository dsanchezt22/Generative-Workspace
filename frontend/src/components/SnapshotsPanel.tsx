"use client";

import type { Snapshot } from "@/lib/types";
import { Icon } from "./Icon";

function timeAgo(iso: string): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const s = Math.floor((Date.now() - t) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

interface Props {
  snapshots: Snapshot[];
  pageName: string;
  onClose: () => void;
  onSave: () => void;
  onRestore: (id: string) => void;
  onDelete: (id: string) => void;
}

export function SnapshotsPanel({ snapshots, pageName, onClose, onSave, onRestore, onDelete }: Props) {
  return (
    // R-1304: full-width sheet below `sm` (the fixed 320px column would
    // otherwise leave the canvas a sliver on a 375px phone) — same panel,
    // same tokens/animation, just full-bleed on a narrow viewport.
    <aside className="fixed top-0 inset-x-0 sm:inset-x-auto sm:right-0 h-screen w-full sm:w-[320px] sm:max-w-[85vw] z-30 bg-[var(--surface)] border-l border-[var(--border)] shadow-2xl shadow-black/40 flex flex-col animate-slide-right">
      <header className="flex items-center gap-2 px-4 h-14 border-b border-[var(--border)] shrink-0">
        <span className="text-sm font-semibold tracking-tight">Snapshots</span>
        <span className="text-xs text-[var(--muted)] truncate min-w-0">· {pageName}</span>
        <button type="button" onClick={onClose} aria-label="Close snapshots"
          className="ml-auto text-[var(--muted)] hover:text-[var(--foreground)] w-6 h-6 grid place-items-center rounded">✕</button>
      </header>
      <div className="p-3 border-b border-[var(--border)]">
        <button type="button" onClick={onSave}
          className="press w-full flex items-center justify-center gap-1.5 rounded-md bg-[var(--accent)] text-[var(--accent-fg)] px-3 py-1.5 text-sm font-medium hover:brightness-110 transition">
          <Icon name="layers" size={15} /> Save this page as a snapshot
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-2">
        {snapshots.length === 0 ? (
          <p className="text-xs text-[var(--muted)] leading-relaxed px-1 pt-2">
            No snapshots yet. Save one before a big change — you can return to exactly how this page looked, anytime.
          </p>
        ) : (
          snapshots.map((s) => (
            <div key={s.id} className="rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] px-3 py-2 flex items-center gap-2">
              <div className="flex-1 min-w-0">
                <div className="text-sm truncate">{s.label}</div>
                <div className="text-[10px] text-[var(--muted)]">{s.module_count} tool{s.module_count === 1 ? "" : "s"} · {timeAgo(s.created_at)}</div>
              </div>
              <button type="button" onClick={() => onRestore(s.id)}
                className="text-xs text-[var(--muted)] hover:text-[var(--accent)] transition shrink-0">Restore</button>
              <button type="button" onClick={() => onDelete(s.id)}
                className="text-xs text-[var(--muted)] hover:text-[var(--danger)] transition shrink-0" aria-label="Delete snapshot">✕</button>
            </div>
          ))
        )}
      </div>
    </aside>
  );
}
