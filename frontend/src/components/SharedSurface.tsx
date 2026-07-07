"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { SharedModule, SharedPageResponse, StoredModule } from "@/lib/types";
import { crossModuleValues } from "@/lib/crossModule";
import { normalizeLayout, type PositionedBox } from "@/lib/sharedLayout";
import { relativeTime } from "@/lib/pulse";
import { resolveIconName } from "@/lib/theme";
import { useAssembly } from "@/lib/useAssembly";
import { Module } from "./Module";
import { Icon } from "./Icon";

// DESIGN-sharing §4g — the public read-only surface. Renders the owner's actual
// spatial arrangement (static absolute layout, normalized to a bounding box) with
// Module variant="shared". No Sidebar / PromptBar / panels / pan-zoom — the
// interaction surface is absent, not disabled. Never calls /api/live.

const noop = () => {};

type LoadState =
  | { phase: "loading" }
  | { phase: "error" }
  | { phase: "ok"; data: SharedPageResponse };

// Whitelisted SharedModule → the StoredModule shape the renderer and the
// crossModule helper read. The absent fields (rev, archived, page_id) are inert
// on a read-only surface.
function toStored(m: SharedModule): StoredModule {
  return { id: m.id, config: m.config, created_at: m.updated_at, updated_at: m.updated_at, archived: false, rev: 0, page_id: null };
}

// One positioned tile. useAssembly runs the signature construct-in on mount
// (reduced-motion → static final state); it targets left/top-positioned wrappers,
// so the GSAP transform clears cleanly without disturbing placement.
function SharedTile({ stored, all, index, box }: { stored: StoredModule; all: StoredModule[]; index: number; box: PositionedBox }) {
  const ref = useAssembly<HTMLDivElement>(index);
  return (
    <div ref={ref} className="absolute" style={{ left: box.x, top: box.y, width: box.width }}>
      <Module
        variant="shared"
        module={stored}
        crossModuleValues={crossModuleValues(all, stored)}
        selected={false}
        onArchive={noop}
        onUndo={noop}
        onSelectForRefine={noop}
        onSelect={noop}
        onDragStart={noop}
        onResizeStart={noop}
      />
    </div>
  );
}

function DeadEnd({ children }: { children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 grid place-items-center bg-[var(--background)] text-center">
      <div className="canvas-grid absolute inset-0 opacity-40" aria-hidden />
      <div className="relative flex flex-col items-center px-6">{children}</div>
    </div>
  );
}

export function SharedSurface({ token }: { token: string }) {
  const [state, setState] = useState<LoadState>({ phase: "loading" });
  // Capture the clock once so the "as of" register stays pure and consistent
  // (the Date.now()-in-render purity lesson).
  const [now] = useState(() => Date.now());

  useEffect(() => {
    let alive = true;
    api
      .fetchShared(token)
      .then((data) => { if (alive) setState({ phase: "ok", data }); })
      // Every failure cause — unknown, revoked, rotated-away, deleted — is one
      // indistinguishable dead end.
      .catch(() => { if (alive) setState({ phase: "error" }); });
    return () => { alive = false; };
  }, [token]);

  if (state.phase === "loading") {
    return (
      <DeadEnd>
        <p className="text-sm font-mono uppercase tracking-wide text-[var(--muted)]">Resolving link…</p>
      </DeadEnd>
    );
  }

  if (state.phase === "error") {
    return (
      <DeadEnd>
        <span className="text-[var(--muted)] opacity-40"><Icon name="grid" size={56} /></span>
        <p className="mt-6 text-sm font-mono uppercase tracking-wide text-[var(--muted)]">This link is no longer active</p>
      </DeadEnd>
    );
  }

  const { page, modules } = state.data;
  const stored = modules.map(toStored);
  const norm = normalizeLayout(stored.map((m) => ({ id: m.id, layout: m.config.layout })));
  const boxes = new Map(norm.boxes.map((b) => [b.id, b]));
  const latest = modules.reduce<string | null>((acc, m) => (acc && acc >= m.updated_at ? acc : m.updated_at), null);

  return (
    <div className="flex flex-col h-screen w-full bg-[var(--background)] text-[var(--foreground)]">
      {/* Slim top bar — icon + name, the persistent read-only badge, wordmark right. */}
      <header className="shrink-0 flex items-center gap-2 h-12 px-4 border-b border-[var(--border)] bg-[var(--background)]/85 backdrop-blur">
        <span className="shrink-0 text-[var(--accent)]"><Icon name={resolveIconName(page.icon, page.name)} size={16} /></span>
        <span className="text-sm font-semibold tracking-tight truncate min-w-0">{page.name}</span>
        <span className="shrink-0 text-[10px] font-mono uppercase tracking-wide text-[var(--muted)] rounded border border-[var(--border)] px-1.5 py-0.5">
          Shared view · read-only{latest ? ` · as of ${relativeTime(latest, now)}` : ""}
        </span>
        <span className="ml-auto shrink-0 flex items-center gap-1 text-xs text-[var(--muted)]">
          <Icon name="sparkles" size={13} /> <span className="hidden sm:inline">Made with Trus</span>
        </span>
      </header>

      {/* Charcoal dotted-grid scroll area holding the static absolute layout. */}
      <div className="canvas-grid relative flex-1 overflow-auto">
        {stored.length === 0 ? (
          <p className="absolute inset-0 grid place-items-center text-sm text-[var(--muted)]">This surface is empty.</p>
        ) : (
          <div className="relative mx-auto my-10" style={{ width: norm.width, minHeight: norm.height }}>
            {stored.map((m, i) => {
              const box = boxes.get(m.id);
              return box ? <SharedTile key={m.id} stored={m} all={stored} index={i} box={box} /> : null;
            })}
          </div>
        )}
      </div>
    </div>
  );
}
