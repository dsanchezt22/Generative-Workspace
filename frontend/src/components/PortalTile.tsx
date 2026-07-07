"use client";

import type { Page, PageOverview } from "@/lib/types";
import { PORTAL_H, PORTAL_W } from "@/lib/portalLayout";
import { resolveIconName, resolvePageAccent } from "@/lib/theme";
import { overviewMeta } from "@/lib/structure";
import { useAssembly } from "@/lib/useAssembly";
import { Icon } from "./Icon";

interface Props {
  page: Page;
  // World position (either the live drag position or the resolved placement).
  pos: { x: number; y: number };
  dragging: boolean;
  overview?: PageOverview;
  // Panel/canvas open-time clock — keeps the component pure (no Date.now in render).
  now: number;
  index: number;
  // Begin a drag/enter gesture (Canvas owns the pointer plumbing).
  onPointerDown: (e: React.PointerEvent) => void;
  // Keyboard Enter/Space → launch (the zoom-in-is-launching tween).
  onEnter: () => void;
}

// A child page rendered as a solid matte "app card" on its parent's canvas
// (V2 SURF §5). Distinct from a module card: it's a place you launch INTO. The
// drag/enter gesture and keyboard affordances are inherited verbatim from the
// former inline tile (R-1305/R-1306); only the surface is restyled. Constructs
// in via the shared assembly (calm — label + body only, no border trace).
export function PortalTile({ page, pos, dragging, overview, now, index, onPointerDown, onEnter }: Props) {
  const ref = useAssembly<HTMLDivElement>(index);
  const theme = resolvePageAccent(page.accent, page.name);
  const modules = overview?.modules ?? 0;
  const underConstruction = modules === 0; // honest dashed "nothing here yet"

  return (
    <div
      ref={ref}
      role="button"
      tabIndex={0}
      aria-label={`Open ${page.name}, ${modules} ${modules === 1 ? "module" : "modules"}`}
      title={`Open ${page.name}`}
      onPointerDown={onPointerDown}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onEnter();
        }
      }}
      className={`portal-tile group absolute flex flex-col justify-between select-none rounded-xl border p-3 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] transition ${
        underConstruction ? "border-dashed" : "border-solid"
      } ${
        dragging
          ? "border-[var(--accent)] cursor-grabbing shadow-lg bg-[var(--surface-elevated)]"
          : "border-[var(--border)] cursor-pointer hover:border-[var(--accent)] bg-[var(--surface-elevated)]/80"
      }`}
      style={{ left: pos.x, top: pos.y, width: PORTAL_W, height: PORTAL_H }}
    >
      {/* SURF-4 identity: a faint GridIcon brand stamp in the corner. */}
      <span
        aria-hidden
        className="absolute bottom-2 right-2 opacity-40 text-[var(--muted)] pointer-events-none"
      >
        <Icon name="grid" size={14} />
      </span>

      <div data-assembly="body" className="flex items-center gap-2.5 min-w-0">
        <span
          className="grid place-items-center w-9 h-9 shrink-0 rounded-lg"
          style={{
            background: `color-mix(in srgb, ${theme.accent} 20%, transparent)`,
            color: theme.accent,
          }}
        >
          <Icon name={resolveIconName(page.icon, page.name)} size={18} />
        </span>
        <span className="min-w-0 flex flex-col gap-0.5">
          <span data-assembly="label" className="block truncate text-sm font-medium text-[var(--foreground)]">
            {page.name}
          </span>
          <span className="block font-mono text-[11px] text-[var(--muted)] truncate">
            {overviewMeta(overview, now)}
          </span>
        </span>
      </div>

      <div className="flex items-center justify-between pr-5 text-[10px] font-mono uppercase tracking-wide text-[var(--muted)]">
        <span aria-hidden>App</span>
        <span className="flex items-center gap-0.5 normal-case tracking-normal text-[11px] group-hover:text-[var(--accent)] group-focus-visible:text-[var(--accent)] transition">
          Open <Icon name="chevronRight" size={12} />
        </span>
      </div>
    </div>
  );
}
