"use client";

import { useEffect } from "react";
import type { Page, PageOverview } from "@/lib/types";
import { resolveIconName, resolvePageAccent } from "@/lib/theme";
import { overviewMeta } from "@/lib/structure";
import { Icon } from "./Icon";

interface Props {
  page: Page;
  parent: Page;
  overview?: PageOverview;
  now: number;
  onBack: () => void;
}

// The in-app frame (V2 SURF §7): a slim strip below the header, shown ONLY when
// the active page has a parent (the root canvas is untouched). Back button +
// accent-tinted icon + page name + the same Geist Mono overview status line the
// tiles use. Charcoal, one bottom border, zero new magenta — the accent stays
// the PromptBar's primary action. Backspace / Alt+ArrowLeft also go back
// (guarded against firing while typing).
export function AppFrame({ page, parent, overview, now, onBack }: Props) {
  const theme = resolvePageAccent(page.accent, page.name);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey) return;
      const el = e.target as HTMLElement | null;
      const typing = !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
      if (typing) return;
      if (e.key === "Backspace" || (e.altKey && e.key === "ArrowLeft")) {
        e.preventDefault();
        onBack();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onBack]);

  return (
    <div className="shrink-0 flex items-center gap-2.5 h-11 px-3 sm:px-5 border-b border-[var(--border)] bg-[var(--background)]/85 backdrop-blur">
      <button
        type="button"
        onClick={onBack}
        aria-label={`Back to ${parent.name}`}
        className="shrink-0 flex items-center gap-1 rounded-md border border-[var(--border)] px-2 py-1 text-xs text-[var(--muted)] hover:text-[var(--foreground)] transition"
      >
        <Icon name="chevronLeft" size={14} />
        <span className="hidden sm:inline">Back</span>
      </button>

      <span
        className="grid place-items-center w-6 h-6 shrink-0 rounded-md"
        style={{ background: `color-mix(in srgb, ${theme.accent} 20%, transparent)`, color: theme.accent }}
        aria-hidden
      >
        <Icon name={resolveIconName(page.icon, page.name)} size={14} />
      </span>
      <h2 className="text-sm font-semibold tracking-tight truncate min-w-0">{page.name}</h2>

      <span className="ml-auto font-mono text-[11px] text-[var(--muted)] truncate hidden sm:block">
        {overviewMeta(overview, now)}
      </span>
      <span aria-hidden className="opacity-40 text-[var(--muted)] shrink-0">
        <Icon name="grid" size={13} />
      </span>
    </div>
  );
}
