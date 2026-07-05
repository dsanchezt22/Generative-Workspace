"use client";

import { useRef, useState } from "react";
import type { StoredModule } from "@/lib/types";
import { resolveIconName } from "@/lib/theme";
import { useDialog } from "@/lib/useDialog";
import { Icon } from "./Icon";
import { ConfirmDialog } from "./ConfirmDialog";

interface Props {
  items: StoredModule[];
  onClose: () => void;
  onRestore: (id: string) => void;
  onDelete: (id: string) => void;
}

export function ArchivedPanel({ items, onClose, onRestore, onDelete }: Props) {
  // R-1102: permanent delete lives only here, behind a confirm.
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const confirmItem = items.find((m) => m.id === confirmId) ?? null;
  // R-1306 dialog floor (mount IS open): focus enters on the header ✕, Tab
  // cycles inside, Escape closes just this panel, focus restores to the
  // sidebar's Archived button on close. While the ConfirmDialog sibling is
  // open, focus sits in that dialog and this trap never fires (no duel).
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const { ref: dialogRef, onKeyDown } = useDialog<HTMLElement>(true, onClose, closeRef);
  // Focus-never-lost: Restore/Delete unmount the row that held focus, so hand
  // focus to the panel's ✕ before the row disappears (a disconnected node
  // would silently drop focus to <body> and break the trap).
  const focusClose = () => closeRef.current?.focus();
  return (
    // ConfirmDialog is a SIBLING of <aside>, not nested inside it: the aside's
    // animate-slide-right animates `transform`, which makes it a containing
    // block for `position: fixed` descendants — a dialog nested inside would
    // be trapped in the panel's 320px column instead of covering the viewport.
    <>
      {/* R-1304: full-width sheet below `sm` (the fixed 320px column would
          otherwise leave the canvas a sliver on a 375px phone) — same panel,
          same tokens/animation, just full-bleed on a narrow viewport. */}
      <aside
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Archived tools"
        onKeyDown={onKeyDown}
        className="fixed top-0 inset-x-0 sm:inset-x-auto sm:right-0 h-screen w-full sm:w-[320px] sm:max-w-[85vw] z-30 bg-[var(--surface)] border-l border-[var(--border)] shadow-2xl shadow-black/40 flex flex-col animate-slide-right"
      >
        <header className="flex items-center gap-2 px-4 h-14 border-b border-[var(--border)] shrink-0">
          <span className="text-sm font-semibold tracking-tight">Archived</span>
          <span className="text-xs text-[var(--muted)]">· {items.length}</span>
          <button ref={closeRef} type="button" onClick={onClose} aria-label="Close archived"
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
                <button type="button" onClick={() => { onRestore(m.id); focusClose(); }}
                  className="text-xs text-[var(--muted)] hover:text-[var(--accent)] transition shrink-0">Restore</button>
                <button type="button" onClick={() => setConfirmId(m.id)}
                  className="text-xs text-[var(--muted)] hover:text-[var(--danger)] transition shrink-0" aria-label="Delete forever">✕</button>
              </div>
            ))
          )}
        </div>
      </aside>
      <ConfirmDialog
        open={confirmId !== null}
        title={`Permanently delete "${confirmItem?.config.title ?? ""}"?`}
        body="This cannot be undone."
        confirmLabel="Delete forever"
        onConfirm={() => {
          if (confirmId) onDelete(confirmId);
          setConfirmId(null);
          // The row's ✕ (the dialog's opener) is gone — ConfirmDialog's
          // restore skips disconnected nodes, so land focus back on the panel
          // after its cleanup runs (hence the timeout).
          window.setTimeout(focusClose, 0);
        }}
        onCancel={() => setConfirmId(null)}
      />
    </>
  );
}
