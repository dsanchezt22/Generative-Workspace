"use client";

import type { ModuleConfig, StoredModule } from "@/lib/types";
import { Module } from "./Module";
import { Icon } from "./Icon";
import { resolveAccent, resolveIconName } from "@/lib/theme";

interface Props {
  module: StoredModule;
  crossModuleValues: Record<string, number>;
  inspectorOpen: boolean;
  onClose: () => void;
  onCommit: (id: string, config: ModuleConfig, delay?: number) => void;
  onUndo: (id: string) => void;
  onRefine: (id: string) => void;
  onSelect: (id: string) => void;
  onEdit: (id: string) => void;
  // R-1102: the card's ✕ archives (undoable), not a hard delete.
  onArchive: (id: string) => void;
}

export function DetailView({ module, crossModuleValues, inspectorOpen, onClose, onCommit, onUndo, onRefine, onSelect, onEdit, onArchive }: Props) {
  const theme = resolveAccent(module.config.accent, module.config.title);
  const icon = resolveIconName(module.config.icon, module.config.title);
  return (
    <div className="fixed inset-0 z-30 bg-[var(--background)] flex flex-col animate-fade">
      <header className="h-14 shrink-0 px-4 flex items-center gap-3 border-b border-[var(--border)]"
        style={{ ["--accent" as string]: theme.accent } as React.CSSProperties}>
        <button type="button" onClick={onClose}
          className="flex items-center gap-1.5 rounded-md border border-[var(--border)] px-2.5 py-1 text-xs text-[var(--muted)] hover:text-[var(--foreground)] transition">
          <Icon name="chevronLeft" size={14} /> Canvas
        </button>
        <span className="shrink-0 grid place-items-center w-6 h-6 rounded-md" style={{ background: "color-mix(in srgb, var(--accent) 20%, transparent)", color: "var(--accent)" }}>
          <Icon name={icon} size={15} />
        </span>
        <span className="text-sm font-semibold tracking-tight truncate">{module.config.title}</span>
      </header>
      <div className="flex-1 overflow-y-auto px-4 py-8" style={{ paddingRight: inspectorOpen ? 320 + 24 : 24 }}>
        <div className="mx-auto w-full max-w-3xl">
          <Module
            module={module}
            variant="detail"
            crossModuleValues={crossModuleValues}
            selected={false}
            onCommit={onCommit}
            onArchive={onArchive}
            onUndo={onUndo}
            onSelectForRefine={onRefine}
            onSelect={onSelect}
            onEdit={onEdit}
            onDragStart={() => {}}
            onResizeStart={() => {}}
          />
        </div>
      </div>
    </div>
  );
}
