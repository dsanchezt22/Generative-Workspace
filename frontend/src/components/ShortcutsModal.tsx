"use client";

import { useDialog } from "@/lib/useDialog";

const SHORTCUTS: [string, string][] = [
  ["⌘ K", "Search & commands"],
  ["⌘ /", "Focus the creation bar"],
  ["⌘ \\", "Toggle the sidebar"],
  ["⌘ D", "Duplicate selected tool"],
  ["⌘ Z", "Undo selected tool's last change"],
  ["F", "Fit canvas to content"],
  ["?", "Show this cheat-sheet"],
  ["Esc", "Close panels / deselect"],
];

export function ShortcutsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  // R-1306 dialog floor: focus enters (the ✕ is the only tabbable, so Tab
  // cycles onto itself), Escape closes just this modal, focus restores to
  // whatever opened it.
  const { ref, onKeyDown } = useDialog<HTMLDivElement>(open, onClose);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 animate-fade" onMouseDown={onClose}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcuts-title"
        onKeyDown={onKeyDown}
        className="w-[min(420px,calc(100%-2rem))] rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-2xl shadow-black/40 p-5 animate-scale-in"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h3 id="shortcuts-title" className="text-sm font-semibold tracking-tight">Keyboard shortcuts</h3>
          <button type="button" onClick={onClose} aria-label="Close" className="text-[var(--muted)] hover:text-[var(--foreground)]">✕</button>
        </div>
        <div className="flex flex-col gap-1.5">
          {SHORTCUTS.map(([key, label]) => (
            <div key={key} className="flex items-center justify-between text-sm">
              <span className="text-[var(--muted)]">{label}</span>
              <kbd className="font-mono text-xs rounded-md border border-[var(--border)] bg-[var(--surface-elevated)] px-2 py-0.5">{key}</kbd>
            </div>
          ))}
        </div>
        <p className="mt-3 text-[10px] text-[var(--muted)]">On Windows/Linux, ⌘ is Ctrl.</p>
      </div>
    </div>
  );
}
