"use client";

import type { StoredModule } from "@/lib/types";
import { resolveIconName } from "@/lib/theme";
import { Icon } from "./Icon";

interface Props {
  items: StoredModule[];
  onClose: () => void;
  onRestore: (id: string) => void;
  onDelete: (id: string) => void;
}

export function ArchivedPanel({ items, onClose, onRestore, onDelete }: Props) {
  return (
    <aside className="fixed top-0 right-0 h-screen w-[320px] max-w-[85vw] z-30 bg-[var(--surface)] border-l border-[var(--border)] shadow-2xl shadow-black/40 flex flex-col animate-slide-right">
      <header className="flex items-center gap-2 px-4 h-14 border-b border-[var(--border)] shrink-0">
        <span className="text-sm font-semibold tracking-tight">Archived</span>
        <span className="text-xs text-[var(--muted)]">· {items.length}</span>
        <button type="button" onClick={onClose} aria-label="Close archived"
          className="ml-auto text-[var(--muted)] hover:text-[var(--foreground)] w-6 h-6 grid place-items-center rounded">✕</button>
      </header>
      <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-2">
        {items.length === 0 ? (
          <p className="text-xs text-[var(--muted)] leading-relaxed px-1 pt-2">
            Nothing archived. Archive a tool from its inspector to tuck it away here — it stays safe and restorable.
          </p>
        ) : (
          items.map((m) => (
            <div key={m.id} className="rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] px-3 py-2 flex items-center gap-2">
              <span className="shrink-0" style={{ color: "var(--accent)" }}><Icon name={resolveIconName(m.config.icon, m.config.title)} size={16} /></span>
              <span className="text-sm flex-1 truncate">{m.config.title}</span>
              <button type="button" onClick={() => onRestore(m.id)}
                className="text-xs text-[var(--muted)] hover:text-[var(--accent)] transition shrink-0">Restore</button>
              <button type="button" onClick={() => onDelete(m.id)}
                className="text-xs text-[var(--muted)] hover:text-[var(--danger)] transition shrink-0" aria-label="Delete forever">✕</button>
            </div>
          ))
        )}
      </div>
    </aside>
  );
}
