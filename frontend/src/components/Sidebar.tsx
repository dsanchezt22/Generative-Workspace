"use client";

import { useEffect, useRef, useState } from "react";
import type { Page } from "@/lib/types";
import { ICON_CHOICES, resolveIconName } from "@/lib/theme";
import { Icon } from "./Icon";

interface Props {
  pages: Page[];
  activePageId: string | null;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onSelect: (id: string) => void;
  onCreate: (parentId?: string | null) => void;
  onRename: (id: string, name: string) => void;
  onSetIcon: (id: string, icon: string) => void;
  // R-1102: request delete — the caller (page.tsx) confirms before deleting.
  onDelete: (page: Page) => void;
  onReorder: (orderedIds: string[]) => void;
  onOpenArchived: () => void;
  onOpenSnapshots: () => void;
  onOpenProfile: () => void;
}

export function Sidebar({
  pages, activePageId, collapsed, onToggleCollapse,
  onSelect, onCreate, onRename, onSetIcon, onDelete, onReorder, onOpenArchived, onOpenSnapshots, onOpenProfile,
}: Props) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [iconForId, setIconForId] = useState<string | null>(null);
  const [dragId, setDragId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const startEdit = (p: Page) => {
    setEditingId(p.id);
    setEditValue(p.name);
    setTimeout(() => inputRef.current?.select(), 0);
  };
  const commitEdit = (id: string) => {
    const name = editValue.trim();
    setEditingId(null);
    const p = pages.find((x) => x.id === id);
    if (name && p && name !== p.name) onRename(id, name);
  };

  const handleDrop = (targetId: string) => {
    if (!dragId || dragId === targetId) return;
    const ids = pages.map((p) => p.id).filter((id) => id !== dragId);
    const idx = ids.indexOf(targetId);
    ids.splice(idx, 0, dragId);
    setDragId(null);
    onReorder(ids);
  };

  const childrenOf = (id: string | null) =>
    pages.filter((p) => (p.parent_id ?? null) === id);

  const renderRow = (page: Page, depth: number) => {
    const active = page.id === activePageId;
    const kids = childrenOf(page.id);
    return (
      <div key={page.id}>
        <div
          draggable={editingId !== page.id}
          onDragStart={() => setDragId(page.id)}
          onDragOver={(e) => e.preventDefault()}
          onDrop={() => handleDrop(page.id)}
          className={`group relative flex items-center gap-1.5 rounded-lg pr-1 py-1 cursor-pointer transition ${
            active ? "bg-[var(--surface-elevated)] text-[var(--foreground)]" : "text-[var(--muted)] hover:bg-[var(--surface-elevated)]/60 hover:text-[var(--foreground)]"
          }`}
          style={{ paddingLeft: `${0.4 + depth * 0.85}rem` }}
          onClick={() => onSelect(page.id)}
        >
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); setIconForId(iconForId === page.id ? null : page.id); }}
            className="w-5 h-5 grid place-items-center shrink-0 rounded hover:bg-[var(--surface)]"
            style={{ color: active ? "var(--accent)" : "var(--muted)" }}
            aria-label="Change page icon"
            title="Change icon"
          >
            <Icon name={resolveIconName(page.icon, page.name)} size={15} />
          </button>

          {editingId === page.id ? (
            <input
              ref={inputRef}
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              onClick={(e) => e.stopPropagation()}
              onBlur={() => commitEdit(page.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter") commitEdit(page.id);
                if (e.key === "Escape") setEditingId(null);
              }}
              className="flex-1 min-w-0 bg-transparent text-sm focus:outline-none border-b border-[var(--accent)]"
              autoFocus
            />
          ) : (
            <span
              className="flex-1 min-w-0 truncate text-sm"
              onDoubleClick={(e) => { e.stopPropagation(); startEdit(page); }}
            >
              {page.name}
            </span>
          )}

          <div className="flex items-center opacity-0 group-hover:opacity-100 transition shrink-0">
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onCreate(page.id); }}
              className="w-5 h-5 grid place-items-center text-xs text-[var(--muted)] hover:text-[var(--foreground)] rounded"
              aria-label="New subpage"
              title="New subpage"
            >
              <Icon name="plus" size={13} />
            </button>
            {pages.length > 1 && (
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); onDelete(page); }}
                className="w-5 h-5 grid place-items-center text-[var(--muted)] hover:text-[var(--danger)] rounded"
                aria-label={`Delete ${page.name}`}
                title="Delete page"
              >
                <Icon name="x" size={12} />
              </button>
            )}
          </div>
        </div>

        {iconForId === page.id && (
          <div className="flex flex-wrap gap-0.5 my-1 mx-1 p-1.5 rounded-lg bg-[var(--surface-elevated)] border border-[var(--border)]">
            {ICON_CHOICES.map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => { onSetIcon(page.id, n); setIconForId(null); }}
                className="w-6 h-6 grid place-items-center rounded text-[var(--muted)] hover:text-[var(--accent)] hover:bg-[var(--surface)]"
                aria-label={`Set icon ${n}`}
              >
                <Icon name={n} size={15} />
              </button>
            ))}
          </div>
        )}

        {kids.map((k) => renderRow(k, depth + 1))}
      </div>
    );
  };

  if (collapsed) {
    return (
      <div className="shrink-0 w-12 border-r border-[var(--border)] bg-[var(--surface)]/60 backdrop-blur flex flex-col items-center py-3 gap-2 transition-[width] duration-200 ease-out overflow-hidden">
        <button
          type="button"
          onClick={onToggleCollapse}
          className="w-8 h-8 grid place-items-center rounded-lg text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--surface-elevated)] transition"
          aria-label="Expand sidebar"
          title="Expand sidebar"
        >
          <Icon name="chevronRight" size={16} />
        </button>
        {childrenOf(null).map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => onSelect(p.id)}
            className={`w-8 h-8 grid place-items-center rounded-lg transition ${
              p.id === activePageId ? "bg-[var(--surface-elevated)] text-[var(--accent)]" : "text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--surface-elevated)]/60"
            }`}
            title={p.name}
          >
            <Icon name={resolveIconName(p.icon, p.name)} size={16} />
          </button>
        ))}
        <button
          type="button"
          onClick={() => onCreate(null)}
          className="w-8 h-8 grid place-items-center rounded-lg text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--surface-elevated)] transition mt-auto"
          aria-label="New page"
          title="New page"
        >
          <Icon name="plus" size={16} />
        </button>
      </div>
    );
  }

  return (
    <div className="shrink-0 w-56 border-r border-[var(--border)] bg-[var(--surface)]/60 backdrop-blur flex flex-col transition-[width] duration-200 ease-out overflow-hidden">
      <div className="flex items-center justify-between px-3 h-14 shrink-0">
        <span className="text-sm font-semibold tracking-tight">Trus</span>
        <button
          type="button"
          onClick={onToggleCollapse}
          className="w-7 h-7 grid place-items-center rounded-lg text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--surface-elevated)] transition"
          aria-label="Collapse sidebar"
          title="Collapse sidebar"
        >
          <Icon name="chevronLeft" size={16} />
        </button>
      </div>
      <div className="px-2 pb-1">
        <p className="text-[10px] uppercase tracking-wide text-[var(--muted)] px-2 mb-1">Pages</p>
      </div>
      <div className="flex-1 overflow-y-auto px-2 flex flex-col gap-0.5">
        {childrenOf(null).map((p) => renderRow(p, 0))}
      </div>
      <div className="p-2 border-t border-[var(--border)] flex flex-col gap-0.5">
        <button
          type="button"
          onClick={() => onCreate(null)}
          className="w-full flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--surface-elevated)] transition"
        >
          <Icon name="plus" size={16} /> New Page
        </button>
        <button
          type="button"
          onClick={onOpenSnapshots}
          className="w-full flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--surface-elevated)] transition"
        >
          <Icon name="layers" size={16} /> Snapshots
        </button>
        <button
          type="button"
          onClick={onOpenArchived}
          className="w-full flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--surface-elevated)] transition"
        >
          <Icon name="archive" size={16} /> Archived
        </button>
        <button
          type="button"
          onClick={onOpenProfile}
          className="w-full flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--surface-elevated)] transition"
          title="What Trus remembers about you"
        >
          <Icon name="user" size={16} /> Profile
        </button>
      </div>
    </div>
  );
}
