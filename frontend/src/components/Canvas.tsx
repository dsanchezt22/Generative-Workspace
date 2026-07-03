"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { CommitModule, StoredModule } from "@/lib/types";
import { Module } from "./Module";

interface Props {
  modules: StoredModule[];
  // Live, in-memory update during a drag/resize gesture (no network).
  onModuleChange: (updated: StoredModule) => void;
  // Persist a settled change through the single saver (optimistic + PATCH).
  onModuleCommit: CommitModule;
  // R-1102: the card's ✕ archives (undoable), not a hard delete.
  onModuleArchive: (id: string) => void;
  onModuleUndo: (id: string) => void;
  onModuleSelectForRefine: (id: string) => void;
  selectedId?: string | null;
  onModuleSelect: (id: string | null) => void;
  onModuleEdit: (id: string) => void;
  onModuleExpand: (id: string) => void;
  activePageId?: string;
  focusRequest?: { id: string; n: number };
  fitRequest?: number;
}

interface View {
  x: number;
  y: number;
  zoom: number;
}

function computeMetric(
  modules: StoredModule[],
  formula: "sum" | "count" | "avg" | "max" | "min",
  sourceComponentId: string,
  excludeId: string,
): number {
  const vals = modules
    .filter((m) => m.id !== excludeId)
    .map((m) => m.config.state[sourceComponentId])
    .filter((v): v is number => typeof v === "number");
  if (vals.length === 0) return 0;
  switch (formula) {
    case "sum": return vals.reduce((a, b) => a + b, 0);
    case "count": return vals.length;
    case "avg": return vals.reduce((a, b) => a + b, 0) / vals.length;
    case "max": return Math.max(...vals);
    case "min": return Math.min(...vals);
  }
}

function crossModuleValues(modules: StoredModule[], module: StoredModule): Record<string, number> {
  const result: Record<string, number> = {};
  for (const c of module.config.components) {
    if (c.type === "metric") {
      result[c.id] = computeMetric(modules, c.formula, c.source_component_id, module.id);
    } else if (c.type === "progress_bar" && c.source_module_id) {
      const src = modules.find((m) => m.id === c.source_module_id);
      if (src && c.bound_to) {
        const v = src.config.state[c.bound_to];
        result[c.id] = typeof v === "number" ? v : 0;
      }
    }
  }
  return result;
}

export function Canvas({
  modules,
  onModuleChange,
  onModuleCommit,
  onModuleArchive,
  onModuleUndo,
  onModuleSelectForRefine,
  selectedId,
  onModuleSelect,
  onModuleEdit,
  onModuleExpand,
  activePageId,
  focusRequest,
  fitRequest,
}: Props) {
  const [view, setView] = useState<View>({ x: 0, y: 0, zoom: 1 });
  const [draggingModule, setDraggingModule] = useState<string | null>(null);
  const [showMiniMap, setShowMiniMap] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const panRef = useRef<{ x: number; y: number; vx: number; vy: number } | null>(
    null,
  );
  const moduleDragRef = useRef<{
    moduleId: string;
    startClient: { x: number; y: number };
    startLayout: { x: number; y: number };
  } | null>(null);
  const moduleResizeRef = useRef<{
    moduleId: string;
    startClient: { x: number; y: number };
    startSize: { width: number; height: number };
  } | null>(null);

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (e.target !== e.currentTarget) return;
      onModuleSelect(null); // clicking empty canvas deselects
      (e.currentTarget as Element).setPointerCapture(e.pointerId);
      panRef.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
    },
    [view, onModuleSelect],
  );

  // Panning only — module drag/resize use window listeners (see below) so a lost
  // pointer can never fall through to a pan ("all modules move at once").
  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!panRef.current) return;
    const { x, y, vx, vy } = panRef.current;
    setView((prev) => ({ ...prev, x: vx + (e.clientX - x), y: vy + (e.clientY - y) }));
  }, []);

  const onPointerUp = useCallback((e: React.PointerEvent) => {
    (e.currentTarget as Element).releasePointerCapture?.(e.pointerId);
    panRef.current = null;
  }, []);

  const onWheel = useCallback((e: React.WheelEvent) => {
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    setView((prev) => {
      const factor = Math.exp(-e.deltaY * 0.0015);
      const nextZoom = Math.min(2, Math.max(0.3, prev.zoom * factor));
      const rect = containerRef.current?.getBoundingClientRect();
      const px = rect ? e.clientX - rect.left : 0;
      const py = rect ? e.clientY - rect.top : 0;
      const wx = (px - prev.x) / prev.zoom;
      const wy = (py - prev.y) / prev.zoom;
      return {
        zoom: nextZoom,
        x: px - wx * nextZoom,
        y: py - wy * nextZoom,
      };
    });
  }, []);

  const viewZoomRef = useRef(view.zoom);
  useEffect(() => {
    viewZoomRef.current = view.zoom;
  }, [view.zoom]);

  const [csize, setCsize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => setCsize({ w: el.clientWidth, h: el.clientHeight });
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Remember pan/zoom per page across reloads and tab switches (PRD 6.2).
  const latestViewRef = useRef(view);
  useEffect(() => { latestViewRef.current = view; }, [view]);
  const currentPageRef = useRef<string | undefined>(activePageId);
  useEffect(() => {
    currentPageRef.current = activePageId;
    if (!activePageId) return;
    try {
      const raw = localStorage.getItem(`trus-view-${activePageId}`);
      setView(raw ? (JSON.parse(raw) as View) : { x: 0, y: 0, zoom: 1 });
    } catch {
      setView({ x: 0, y: 0, zoom: 1 });
    }
  }, [activePageId]);
  useEffect(() => {
    const pid = currentPageRef.current;
    if (!pid) return;
    const t = setTimeout(() => {
      try { localStorage.setItem(`trus-view-${pid}`, JSON.stringify(view)); } catch {}
    }, 300);
    return () => clearTimeout(t);
  }, [view]);

  const latestModulesRef = useRef(modules);
  useEffect(() => {
    latestModulesRef.current = modules;
  }, [modules]);

  // Center the camera on a module when search/command asks to jump to it.
  useEffect(() => {
    if (!focusRequest) return;
    const m = modules.find((x) => x.id === focusRequest.id);
    const rect = containerRef.current?.getBoundingClientRect();
    if (!m || !rect) return;
    const { x, y, width, height } = m.config.layout;
    const zoom = 1;
    setView({ zoom, x: rect.width / 2 - (x + width / 2) * zoom, y: rect.height / 2 - (y + height / 2) * zoom });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusRequest?.n]);

  // Module drag/resize run on WINDOW listeners for the duration of the gesture —
  // reliable regardless of zoom, re-renders, or what's under the cursor, and it
  // can never trigger a canvas pan.
  const winMove = useCallback((e: PointerEvent) => {
    const z = viewZoomRef.current || 1;
    if (moduleDragRef.current) {
      const { moduleId, startClient, startLayout } = moduleDragRef.current;
      const m = latestModulesRef.current.find((mm) => mm.id === moduleId);
      if (!m) return;
      onModuleChange({
        ...m,
        config: { ...m.config, layout: { ...m.config.layout, x: startLayout.x + (e.clientX - startClient.x) / z, y: startLayout.y + (e.clientY - startClient.y) / z } },
      });
    } else if (moduleResizeRef.current) {
      const { moduleId, startClient, startSize } = moduleResizeRef.current;
      const m = latestModulesRef.current.find((mm) => mm.id === moduleId);
      if (!m) return;
      onModuleChange({
        ...m,
        config: { ...m.config, layout: { ...m.config.layout, width: Math.max(240, startSize.width + (e.clientX - startClient.x) / z), height: Math.max(160, startSize.height + (e.clientY - startClient.y) / z) } },
      });
    }
  }, [onModuleChange]);

  const winUp = useCallback(() => {
    window.removeEventListener("pointermove", winMove);
    window.removeEventListener("pointerup", winUp);
    window.removeEventListener("pointercancel", winUp);
    const ref = moduleDragRef.current ?? moduleResizeRef.current;
    moduleDragRef.current = null;
    moduleResizeRef.current = null;
    setDraggingModule(null);
    if (ref) {
      const m = latestModulesRef.current.find((mm) => mm.id === ref.moduleId);
      // Commit the settled layout through the single saver. m.config already
      // carries any state edits made just before the drag (they merge into one
      // PATCH), retiring the edit-then-drag snap-back (R-602 AC #3).
      if (m) onModuleCommit(m.id, m.config);
    }
  }, [winMove, onModuleCommit]);

  const beginGesture = useCallback((e: React.PointerEvent) => {
    e.stopPropagation();
    e.preventDefault();
    setDraggingModule("active");
    window.addEventListener("pointermove", winMove);
    window.addEventListener("pointerup", winUp);
    window.addEventListener("pointercancel", winUp);
  }, [winMove, winUp]);

  const handleModuleDragStart = useCallback(
    (e: React.PointerEvent, moduleId: string) => {
      const m = latestModulesRef.current.find((mm) => mm.id === moduleId);
      if (!m) return;
      moduleResizeRef.current = null;
      moduleDragRef.current = {
        moduleId,
        startClient: { x: e.clientX, y: e.clientY },
        startLayout: { x: m.config.layout.x, y: m.config.layout.y },
      };
      beginGesture(e);
    },
    [beginGesture],
  );

  const handleResizeStart = useCallback(
    (e: React.PointerEvent, moduleId: string) => {
      const m = latestModulesRef.current.find((mm) => mm.id === moduleId);
      if (!m) return;
      moduleDragRef.current = null;
      moduleResizeRef.current = {
        moduleId,
        startClient: { x: e.clientX, y: e.clientY },
        startSize: { width: m.config.layout.width, height: m.config.layout.height },
      };
      beginGesture(e);
    },
    [beginGesture],
  );

  const ZOOM_MIN = 0.3, ZOOM_MAX = 2;
  const clampZoom = (z: number) => Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z));

  // Zoom toward the viewport center by a multiplicative factor.
  const zoomBy = useCallback((factor: number) => {
    const rect = containerRef.current?.getBoundingClientRect();
    const cx = rect ? rect.width / 2 : 0;
    const cy = rect ? rect.height / 2 : 0;
    setView((prev) => {
      const nz = clampZoom(prev.zoom * factor);
      const wx = (cx - prev.x) / prev.zoom;
      const wy = (cy - prev.y) / prev.zoom;
      return { zoom: nz, x: cx - wx * nz, y: cy - wy * nz };
    });
  }, []);

  // Content-sized cards report height:0 in their layout, so we measure the real
  // rendered DOM height for correct fit/minimap framing (otherwise the content
  // box is ~0 tall and the fit zooms way in — modules look "overly big").
  const heightsRef = useRef<Record<string, number>>({});
  const [heights, setHeights] = useState<Record<string, number>>({});
  const reportHeight = useCallback((id: string, h: number) => {
    if (Math.abs((heightsRef.current[id] ?? 0) - h) < 1) return;
    heightsRef.current[id] = h;
    setHeights((p) => ({ ...p, [id]: h }));
  }, []);
  const heightOf = useCallback(
    (m: StoredModule) => heightsRef.current[m.id] || m.config.layout.height || 320,
    [],
  );

  // Bounding box of all modules on the page (world coordinates).
  const contentBounds = useCallback(() => {
    if (modules.length === 0) return null;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const m of modules) {
      const { x, y, width } = m.config.layout;
      minX = Math.min(minX, x); minY = Math.min(minY, y);
      maxX = Math.max(maxX, x + (width || 372)); maxY = Math.max(maxY, y + heightOf(m));
    }
    return { minX, minY, maxX, maxY };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modules, heights, heightOf]);

  const fitToContent = useCallback(() => {
    const rect = containerRef.current?.getBoundingClientRect();
    const b = contentBounds();
    if (!rect || !b) { setView({ x: 0, y: 0, zoom: 1 }); return; }
    const pad = 80;
    const cw = b.maxX - b.minX + pad * 2;
    const ch = b.maxY - b.minY + pad * 2;
    // Never magnify past 100% when fitting — upscaling is what made freshly
    // generated tools look "overly big". We only ever zoom out to fit.
    const zoom = Math.min(1, clampZoom(Math.min(rect.width / cw, rect.height / ch)));
    const cxWorld = (b.minX + b.maxX) / 2;
    const cyWorld = (b.minY + b.maxY) / 2;
    setView({
      x: rect.width / 2 - cxWorld * zoom,
      y: rect.height / 2 - cyWorld * zoom + 20, // bias down so content clears the top bar
      zoom,
    });
  }, [contentBounds]);

  // Run the fit through a ref so it always uses the latest measured heights,
  // while only firing when a fit is explicitly requested (not on every measure).
  const fitToContentRef = useRef(fitToContent);
  useEffect(() => { fitToContentRef.current = fitToContent; });
  useEffect(() => {
    if (fitRequest) fitToContentRef.current();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitRequest]);

  return (
    <div
      ref={containerRef}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onWheel={onWheel}
      className="canvas-grid relative flex-1 overflow-hidden cursor-grab active:cursor-grabbing touch-none"
      style={{ backgroundPosition: `${view.x}px ${view.y}px` }}
    >
      <div
        className="absolute inset-0 origin-top-left"
        style={{
          transform: `translate(${view.x}px, ${view.y}px) scale(${view.zoom})`,
          transformOrigin: "0 0",
          pointerEvents: "none",
        }}
      >
        <div style={{ pointerEvents: "auto" }} className="relative">
          {modules.map((m, i) => (
            <Module
              key={m.id}
              module={m}
              index={i}
              onMeasure={reportHeight}
              crossModuleValues={crossModuleValues(modules, m)}
              selected={m.id === selectedId}
              onCommit={onModuleCommit}
              onArchive={onModuleArchive}
              onUndo={onModuleUndo}
              onSelectForRefine={onModuleSelectForRefine}
              onSelect={onModuleSelect}
              onEdit={onModuleEdit}
              onExpand={onModuleExpand}
              onDragStart={handleModuleDragStart}
              onResizeStart={handleResizeStart}
            />
          ))}
        </div>
      </div>

      {showMiniMap && (() => {
        const b = contentBounds();
        if (!b) return null;
        const MM_W = 180, MM_H = 120, MM_PAD = 60;
        const bw = (b.maxX - b.minX) + MM_PAD * 2;
        const bh = (b.maxY - b.minY) + MM_PAD * 2;
        const s = Math.min(MM_W / bw, MM_H / bh);
        const ox = (MM_W - bw * s) / 2;
        const oy = (MM_H - bh * s) / 2;
        const toMM = (wx: number, wy: number) => ({
          x: ox + (wx - (b.minX - MM_PAD)) * s,
          y: oy + (wy - (b.minY - MM_PAD)) * s,
        });
        const vp = toMM(-view.x / view.zoom, -view.y / view.zoom);
        const onMiniClick = (e: React.MouseEvent) => {
          const box = (e.currentTarget as HTMLElement).getBoundingClientRect();
          const wx = (b.minX - MM_PAD) + (e.clientX - box.left - ox) / s;
          const wy = (b.minY - MM_PAD) + (e.clientY - box.top - oy) / s;
          setView((prev) => ({ ...prev, x: csize.w / 2 - wx * prev.zoom, y: csize.h / 2 - wy * prev.zoom }));
        };
        return (
          <div
            className="absolute bottom-16 right-4 rounded-lg border border-[var(--border)] bg-[var(--surface)]/95 backdrop-blur overflow-hidden shadow z-10 cursor-pointer"
            style={{ width: MM_W, height: MM_H }}
            onClick={onMiniClick}
            aria-label="Mini-map"
          >
            {modules.map((m) => {
              const p = toMM(m.config.layout.x, m.config.layout.y);
              return (
                <div
                  key={m.id}
                  className="absolute rounded-[2px]"
                  style={{
                    left: p.x, top: p.y,
                    width: Math.max(3, (m.config.layout.width || 372) * s),
                    height: Math.max(3, heightOf(m) * s),
                    background: "color-mix(in srgb, var(--accent) 70%, transparent)",
                  }}
                />
              );
            })}
            <div
              className="absolute rounded-[2px] border border-[var(--foreground)]/60 bg-[var(--foreground)]/5"
              style={{ left: vp.x, top: vp.y, width: (csize.w / view.zoom) * s, height: (csize.h / view.zoom) * s }}
            />
          </div>
        );
      })()}

      <div className="absolute bottom-4 right-4 flex items-center gap-0.5 rounded-full bg-[var(--surface)]/85 backdrop-blur px-1.5 py-1 border border-[var(--border)] text-xs text-[var(--muted)] z-10">
        <button type="button" onClick={fitToContent} title="Fit to content" aria-label="Fit to content"
          className="hover:text-[var(--foreground)] transition w-6 h-6 grid place-items-center rounded">⤢</button>
        <span className="w-px h-4 bg-[var(--border)]" aria-hidden />
        <button type="button" onClick={() => zoomBy(1 / 1.2)} title="Zoom out" aria-label="Zoom out"
          className="hover:text-[var(--foreground)] transition w-6 h-6 grid place-items-center rounded text-sm">−</button>
        <button type="button" onClick={() => setView({ x: 0, y: 0, zoom: 1 })} title="Reset zoom" aria-label="Reset view"
          className="hover:text-[var(--foreground)] transition px-1 h-6 grid place-items-center rounded font-mono min-w-[3rem]">{Math.round(view.zoom * 100)}%</button>
        <button type="button" onClick={() => zoomBy(1.2)} title="Zoom in" aria-label="Zoom in"
          className="hover:text-[var(--foreground)] transition w-6 h-6 grid place-items-center rounded text-sm">+</button>
        <span className="w-px h-4 bg-[var(--border)]" aria-hidden />
        <button type="button" onClick={() => setShowMiniMap((v) => !v)} title="Mini-map" aria-label="Toggle mini-map"
          className={`transition w-6 h-6 grid place-items-center rounded ${showMiniMap ? "text-[var(--accent)]" : "hover:text-[var(--foreground)]"}`}>▦</button>
      </div>

      {draggingModule && (
        <div className="pointer-events-none absolute inset-0" />
      )}
    </div>
  );
}
