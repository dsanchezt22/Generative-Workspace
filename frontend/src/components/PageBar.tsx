"use client";

import { useRef, useState } from "react";
import type { Page } from "@/lib/types";
import { api } from "@/lib/api";

interface Props {
  pages: Page[];
  activePageId: string;
  onSelectPage: (id: string) => void;
  onPageCreated: (page: Page) => void;
  onPageRenamed: (page: Page) => void;
  onPageDeleted: (id: string) => void;
}

export function PageBar({
  pages,
  activePageId,
  onSelectPage,
  onPageCreated,
  onPageRenamed,
  onPageDeleted,
}: Props) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);

  const startEdit = (page: Page) => {
    setEditingId(page.id);
    setEditValue(page.name);
    setTimeout(() => inputRef.current?.select(), 0);
  };

  const commitEdit = async (id: string) => {
    const name = editValue.trim();
    setEditingId(null);
    if (!name) return;
    const page = pages.find((p) => p.id === id);
    if (page && name !== page.name) {
      try {
        const updated = await api.renamePage(id, name);
        onPageRenamed(updated);
      } catch {
        /* ignore */
      }
    }
  };

  const handleAdd = async () => {
    const name = `Page ${pages.length + 1}`;
    try {
      const page = await api.createPage(name);
      onPageCreated(page);
      // immediately start editing the new page name
      startEdit(page);
    } catch {
      /* ignore */
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await api.deletePage(id);
      onPageDeleted(id);
    } catch {
      /* ignore — last page returns 409 */
    }
  };

  const tab =
    "group relative flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-t-lg border-b-0 transition select-none";

  return (
    <div className="absolute top-12 left-0 right-0 z-10 flex items-end px-6 pointer-events-none">
      <div className="flex items-end gap-0.5 pointer-events-auto">
        {pages.map((page) => {
          const active = page.id === activePageId;
          return (
            <div
              key={page.id}
              className={`${tab} ${
                active
                  ? "bg-[var(--surface)] border border-[var(--border)] text-[var(--foreground)]"
                  : "bg-transparent border border-transparent text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--surface)]/60"
              }`}
            >
              <button
                type="button"
                onClick={() => onSelectPage(page.id)}
                onDoubleClick={() => startEdit(page)}
                className="focus:outline-none"
              >
                {editingId === page.id ? (
                  <input
                    ref={inputRef}
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    onBlur={() => commitEdit(page.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void commitEdit(page.id);
                      if (e.key === "Escape") setEditingId(null);
                    }}
                    className="bg-transparent focus:outline-none w-[80px] text-xs"
                    autoFocus
                  />
                ) : (
                  <span className="max-w-[120px] truncate">{page.name}</span>
                )}
              </button>
              {active && pages.length > 1 && (
                <button
                  type="button"
                  onClick={() => handleDelete(page.id)}
                  className="opacity-0 group-hover:opacity-60 hover:!opacity-100 transition text-[var(--muted)] hover:text-[var(--danger)] text-[10px] leading-none"
                  aria-label={`Delete ${page.name}`}
                  title="Delete page"
                >
                  ✕
                </button>
              )}
            </div>
          );
        })}
        <button
          type="button"
          onClick={handleAdd}
          className="px-2 py-1.5 text-xs text-[var(--muted)] hover:text-[var(--foreground)] transition rounded-t-lg border border-transparent hover:border-[var(--border)] hover:bg-[var(--surface)]/60"
          title="New page"
          aria-label="New page"
        >
          +
        </button>
      </div>
    </div>
  );
}
