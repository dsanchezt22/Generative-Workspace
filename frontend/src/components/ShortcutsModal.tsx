"use client";

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
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 animate-fade" onMouseDown={onClose}>
      <div className="w-[min(420px,calc(100%-2rem))] rounded-lg border border-[var(--border)] bg-[var(--surface)] shadow-2xl shadow-black/40 p-5 animate-scale-in"
        onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold tracking-tight">Keyboard shortcuts</h3>
          <button type="button" onClick={onClose} aria-label="Close" className="text-[var(--muted)] hover:text-[var(--foreground)]">✕</button>
        </div>
        <div className="flex flex-col gap-1.5">
          {SHORTCUTS.map(([key, label]) => (
            <div key={key} className="flex items-center justify-between text-sm">
              <span className="text-[var(--muted)]">{label}</span>
              <kbd className="font-mono text-xs rounded-sm border border-[var(--border)] bg-[var(--surface-elevated)] px-2 py-0.5">{key}</kbd>
            </div>
          ))}
        </div>
        <p className="mt-3 text-[10px] text-[var(--muted)]">On Windows/Linux, ⌘ is Ctrl.</p>
      </div>
    </div>
  );
}
