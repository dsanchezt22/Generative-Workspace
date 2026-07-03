"use client";

import { useEffect, useRef } from "react";

interface Props {
  open: boolean;
  title: string;
  body: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}

// R-1102: the one confirm surface for destructive, irreversible actions (page
// delete, permanent module delete). Overlay/panel classes match ShortcutsModal
// so it reads as native to the app, not a bolted-on browser confirm().
export function ConfirmDialog({ open, title, body, confirmLabel, onConfirm, onCancel }: Props) {
  const cancelRef = useRef<HTMLButtonElement | null>(null);
  // Keep the latest onCancel without re-running the open-effect on every parent
  // render (page.tsx re-renders often — e.g. saveStatus — which would otherwise
  // re-steal focus from the dialog and thrash the Escape listener).
  const onCancelRef = useRef(onCancel);
  useEffect(() => { onCancelRef.current = onCancel; }, [onCancel]);

  useEffect(() => {
    if (!open) return;
    cancelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); onCancelRef.current(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 animate-fade" onMouseDown={onCancel}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-body"
        className="w-[min(420px,calc(100%-2rem))] rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-2xl shadow-black/40 p-5 animate-scale-in"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h3 id="confirm-dialog-title" className="text-sm font-semibold tracking-tight mb-2">{title}</h3>
        <p id="confirm-dialog-body" className="text-sm text-[var(--muted)] leading-relaxed mb-4">{body}</p>
        <div className="flex items-center justify-end gap-2">
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            className="rounded-md border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--muted)] hover:text-[var(--foreground)] transition"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="rounded-md bg-[var(--danger)] text-white px-3 py-1.5 text-xs font-medium hover:brightness-110 transition"
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
