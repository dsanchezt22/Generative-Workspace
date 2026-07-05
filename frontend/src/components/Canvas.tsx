"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { CommitModule, Page, StoredModule } from "@/lib/types";
import { resolveIconName } from "@/lib/theme";
import {
  rasterScale,
  screenToWorld,
  strokeBounds,
  type Bounds,
  type Point,
  type Stroke,
} from "@/lib/sketchExport";
import {
  clampZoom,
  pinchZoomFactor,
  pointerDistance,
  pointerMidpoint,
  zoomTowardPoint,
} from "@/lib/pinchZoom";
import { PORTAL_H, PORTAL_W, portalPosition } from "@/lib/portalLayout";
import { Icon } from "./Icon";
import { Module } from "./Module";

// R-221: the sketch snap's interpretation instruction, sent as the `hint` the
// backend folds into the vision model's message (bounded server-side to ~200).
const SKETCH_HINT =
  "Hand-drawn wireframe sketch of a tool layout — interpret boxes as fields/components, labels as their names, lines as groupings.";
const SNAP_PAD = 24; // world-px margin around the sketch bbox for the raster
const ERASE_RADIUS = 14; // screen-px reach of the stroke eraser (scaled by zoom)

// The app's charcoal bg + ink, read live so the raster matches whatever theme is
// active (the vision model sees strokes-on-charcoal like the real UI).
function readSketchColors(): { ink: string; bg: string } {
  if (typeof window === "undefined") return { ink: "#f0efed", bg: "#181818" };
  const cs = getComputedStyle(document.documentElement);
  return {
    ink: cs.getPropertyValue("--foreground").trim() || "#f0efed",
    bg: cs.getPropertyValue("--background").trim() || "#181818",
  };
}

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
  // R-221-223: snapped sketch → generated modules land on the canvas via the
  // parent's normal new-module path (placement + fit). Optional so Canvas renders
  // without it (the Sketch toggle simply won't reach generation).
  onSketchModules?: (modules: StoredModule[]) => void;
  // R-502/R-504: child pages (parent_id === activePageId) render as enterable
  // world-coord portal tiles BELOW the module layer. `childCounts` feeds each
  // tile's cheap "N tools" preview; enter switches to that page; a drag persists
  // the tile's placement (portal_x/portal_y). All optional so Canvas renders
  // without portal wiring.
  childPages?: Page[];
  childCounts?: Record<string, number>;
  onEnterPortal?: (pageId: string) => void;
  onPortalMove?: (pageId: string, x: number, y: number) => void;
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
  onSketchModules,
  childPages,
  childCounts,
  onEnterPortal,
  onPortalMove,
}: Props) {
  const [view, setView] = useState<View>({ x: 0, y: 0, zoom: 1 });
  const [draggingModule, setDraggingModule] = useState<string | null>(null);
  const [showMiniMap, setShowMiniMap] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const panRef = useRef<{ x: number; y: number; vx: number; vy: number } | null>(
    null,
  );
  // R-1304: two-finger pinch-zoom. `activePointersRef` tracks every active
  // pointer's last known screen position (insertion order = touch order, so
  // a 3rd incidental touch during a pinch never displaces the original two).
  // `pinchDistRef` holds the last sampled inter-finger distance so each move
  // event yields a per-step zoom factor (the same per-tick pattern onWheel
  // uses below) instead of a cumulative ratio from gesture start, which would
  // drift if a sample were ever missed. Null when not mid-pinch.
  const activePointersRef = useRef<Map<number, Point>>(new Map());
  const pinchDistRef = useRef<number | null>(null);
  const ZOOM_MIN = 0.3, ZOOM_MAX = 2;
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
      (e.currentTarget as Element).setPointerCapture(e.pointerId);
      activePointersRef.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (activePointersRef.current.size === 2) {
        // A second touch lands (possibly mid-pan): hand off to pinch-zoom
        // cleanly — a stale pan delta must never fight the pinch.
        panRef.current = null;
        const [p1, p2] = Array.from(activePointersRef.current.values());
        pinchDistRef.current = pointerDistance(p1, p2);
        return;
      }
      if (activePointersRef.current.size > 2) return; // an extra touch doesn't restart the gesture
      onModuleSelect(null); // a genuine single-pointer tap/click on empty canvas deselects
      panRef.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
    },
    [view, onModuleSelect],
  );

  // Panning only — module drag/resize use window listeners (see below) so a lost
  // pointer can never fall through to a pan ("all modules move at once").
  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (activePointersRef.current.has(e.pointerId)) {
      activePointersRef.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    }
    if (activePointersRef.current.size === 2 && pinchDistRef.current !== null) {
      // R-1304: zoom by each step's distance ratio, toward the fingers'
      // midpoint — reuses the same `zoomTowardPoint` anchor math onWheel and
      // the +/- buttons use, so the clamp + view-update behavior is identical.
      const [p1, p2] = Array.from(activePointersRef.current.values());
      const dist = pointerDistance(p1, p2);
      const factor = pinchZoomFactor(pinchDistRef.current, dist);
      pinchDistRef.current = dist;
      const rect = containerRef.current?.getBoundingClientRect();
      const mid = pointerMidpoint(p1, p2);
      const midLocal = { x: mid.x - (rect?.left ?? 0), y: mid.y - (rect?.top ?? 0) };
      setView((prev) => zoomTowardPoint(prev, factor, midLocal, ZOOM_MIN, ZOOM_MAX));
      return;
    }
    if (!panRef.current) return;
    const { x, y, vx, vy } = panRef.current;
    setView((prev) => ({ ...prev, x: vx + (e.clientX - x), y: vy + (e.clientY - y) }));
  }, []);

  // Any tracked pointer ending — one lifted mid-pinch, or the single pan
  // finger — exits whatever gesture is active cleanly rather than trying to
  // resume a pan from a stale reference point (which would jump the canvas).
  const onPointerUp = useCallback((e: React.PointerEvent) => {
    (e.currentTarget as Element).releasePointerCapture?.(e.pointerId);
    activePointersRef.current.delete(e.pointerId);
    pinchDistRef.current = null;
    panRef.current = null;
  }, []);

  const onWheel = useCallback((e: React.WheelEvent) => {
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    const factor = Math.exp(-e.deltaY * 0.0015);
    const rect = containerRef.current?.getBoundingClientRect();
    const point = { x: rect ? e.clientX - rect.left : 0, y: rect ? e.clientY - rect.top : 0 };
    setView((prev) => zoomTowardPoint(prev, factor, point, ZOOM_MIN, ZOOM_MAX));
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

  // ---------------------------------------------------------- portals (R-502) -
  // Child-page portal tiles are world-coord objects on a layer BELOW the modules
  // (rendered first → modules paint on top; a module drag always wins where they
  // overlap). Drag/enter mirror the module gesture: WINDOW listeners for the
  // gesture's life (reliable regardless of zoom/re-render, can never trigger a
  // canvas pan). A pointerdown that moves past a small threshold is a DRAG (persists
  // portal_x/portal_y on drop); one that doesn't is a CLICK (enter the page).
  const [portalDrag, setPortalDrag] = useState<{ id: string; x: number; y: number } | null>(null);
  const portalDragRef = useRef<{
    pageId: string;
    startClient: { x: number; y: number };
    startPos: { x: number; y: number };
    cur: { x: number; y: number };
    moved: boolean;
  } | null>(null);
  // Latched props so the window-scoped up handler never fires a stale callback.
  const onEnterPortalRef = useRef(onEnterPortal);
  const onPortalMoveRef = useRef(onPortalMove);
  useEffect(() => { onEnterPortalRef.current = onEnterPortal; }, [onEnterPortal]);
  useEffect(() => { onPortalMoveRef.current = onPortalMove; }, [onPortalMove]);

  const portalWinMove = useCallback((e: PointerEvent) => {
    const ref = portalDragRef.current;
    if (!ref) return;
    const z = viewZoomRef.current || 1;
    if (Math.abs(e.clientX - ref.startClient.x) > 3 || Math.abs(e.clientY - ref.startClient.y) > 3) {
      ref.moved = true;
    }
    ref.cur = {
      x: ref.startPos.x + (e.clientX - ref.startClient.x) / z,
      y: ref.startPos.y + (e.clientY - ref.startClient.y) / z,
    };
    setPortalDrag({ id: ref.pageId, x: ref.cur.x, y: ref.cur.y });
  }, []);

  // One handler for pointerup AND pointercancel (self-referencing removal, same
  // shape as the module winUp above): a settled drag persists the new placement;
  // a no-move pointerup enters the page; a cancel never enters.
  const portalWinUp = useCallback((e: PointerEvent) => {
    window.removeEventListener("pointermove", portalWinMove);
    window.removeEventListener("pointerup", portalWinUp);
    window.removeEventListener("pointercancel", portalWinUp);
    const ref = portalDragRef.current;
    portalDragRef.current = null;
    setPortalDrag(null);
    if (!ref) return;
    if (ref.moved) onPortalMoveRef.current?.(ref.pageId, ref.cur.x, ref.cur.y);
    else if (e.type !== "pointercancel") onEnterPortalRef.current?.(ref.pageId);
  }, [portalWinMove]);

  const startPortalDrag = useCallback(
    (e: React.PointerEvent, pageId: string, pos: { x: number; y: number }) => {
      // Stop the canvas from panning / a module from reacting to this pointer.
      e.stopPropagation();
      e.preventDefault();
      portalDragRef.current = {
        pageId,
        startClient: { x: e.clientX, y: e.clientY },
        startPos: pos,
        cur: { ...pos },
        moved: false,
      };
      window.addEventListener("pointermove", portalWinMove);
      window.addEventListener("pointerup", portalWinUp);
      window.addEventListener("pointercancel", portalWinUp);
    },
    [portalWinMove, portalWinUp],
  );

  // Zoom toward the viewport center by a multiplicative factor (the +/-
  // buttons). Shares `zoomTowardPoint` with wheel-zoom and pinch-zoom
  // (R-1304) — the same "keep the world point under `screenPoint` fixed"
  // anchor math, just centered instead of at the cursor/fingers.
  const zoomBy = useCallback((factor: number) => {
    const rect = containerRef.current?.getBoundingClientRect();
    const point = { x: rect ? rect.width / 2 : 0, y: rect ? rect.height / 2 : 0 };
    setView((prev) => zoomTowardPoint(prev, factor, point, ZOOM_MIN, ZOOM_MAX));
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

  // Bounding box of all modules AND child portal tiles on the page (world
  // coordinates). Portals live in a negative-Y shelf above the modules, so
  // including them here keeps fit-to-content framing them (otherwise the shelf
  // sits above the viewport) — this is what makes a fresh child portal visible on
  // an otherwise-populated parent instead of stranded off-screen.
  const contentBounds = useCallback(() => {
    const kids = childPages ?? [];
    if (modules.length === 0 && kids.length === 0) return null;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const m of modules) {
      const { x, y, width } = m.config.layout;
      minX = Math.min(minX, x); minY = Math.min(minY, y);
      maxX = Math.max(maxX, x + (width || 372)); maxY = Math.max(maxY, y + heightOf(m));
    }
    kids.forEach((p, i) => {
      const pos = portalPosition(p, i);
      minX = Math.min(minX, pos.x); minY = Math.min(minY, pos.y);
      maxX = Math.max(maxX, pos.x + PORTAL_W); maxY = Math.max(maxY, pos.y + PORTAL_H);
    });
    return { minX, minY, maxX, maxY };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modules, heights, heightOf, childPages]);

  const fitToContent = useCallback(() => {
    const rect = containerRef.current?.getBoundingClientRect();
    const b = contentBounds();
    if (!rect || !b) { setView({ x: 0, y: 0, zoom: 1 }); return; }
    const pad = 80;
    const cw = b.maxX - b.minX + pad * 2;
    const ch = b.maxY - b.minY + pad * 2;
    // Never magnify past 100% when fitting — upscaling is what made freshly
    // generated tools look "overly big". We only ever zoom out to fit.
    const zoom = Math.min(1, clampZoom(Math.min(rect.width / cw, rect.height / ch), ZOOM_MIN, ZOOM_MAX));
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

  // ------------------------------------------------------------ sketch (R-221) -
  // A transparent full-viewport overlay drawn in WORLD coordinates: strokes are
  // stored as world-space polylines and rendered through the SAME pan/zoom the
  // modules use, so a stroke stays put when you pan/zoom. While sketch mode is on
  // the overlay sits above everything and captures every pointer event, which
  // suspends canvas pan/drag/module-interaction (they only fire on the container
  // below). The sketch is ephemeral (R-223): consumed by Snap, cleared on cancel.
  const [sketchMode, setSketchMode] = useState(false);
  const [tool, setTool] = useState<"pen" | "eraser">("pen");
  const [strokes, setStrokes] = useState<Stroke[]>([]);
  const [snapping, setSnapping] = useState(false);
  const [sketchError, setSketchError] = useState<string | null>(null);
  const overlayRef = useRef<HTMLCanvasElement | null>(null);
  const draftRef = useRef<Point[] | null>(null);
  const drawingRef = useRef(false);
  const strokesRef = useRef<Stroke[]>(strokes);
  useEffect(() => { strokesRef.current = strokes; }, [strokes]);
  const sketchModeRef = useRef(sketchMode);
  useEffect(() => { sketchModeRef.current = sketchMode; }, [sketchMode]);
  const toolRef = useRef(tool);
  useEffect(() => { toolRef.current = tool; }, [tool]);

  // Full redraw of the overlay: clear, then draw every stored stroke (plus the
  // in-progress draft) in SCREEN space at a constant 2px, positioning each world
  // point through the current view — so line weight never distorts with zoom and
  // strokes track the world on pan/zoom.
  const redrawSketch = useCallback(() => {
    const canvas = overlayRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const v = latestViewRef.current;
    ctx.strokeStyle = readSketchColors().ink;
    ctx.lineWidth = 2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.globalAlpha = 0.8;
    const draw = (s: Point[]) => {
      if (s.length === 0) return;
      ctx.beginPath();
      for (let i = 0; i < s.length; i++) {
        const sx = v.x + s[i].x * v.zoom;
        const sy = v.y + s[i].y * v.zoom;
        if (i === 0) ctx.moveTo(sx, sy);
        else ctx.lineTo(sx, sy);
      }
      if (s.length === 1) ctx.lineTo(v.x + s[0].x * v.zoom + 0.1, v.y + s[0].y * v.zoom + 0.1);
      ctx.stroke();
    };
    for (const s of strokesRef.current) draw(s);
    if (draftRef.current) draw(draftRef.current);
    ctx.globalAlpha = 1;
  }, []);

  // Redraw whenever the overlay is shown, the view changes (pan/zoom), the
  // committed strokes change (a new stroke, an erase, or a clear), or the
  // container resizes.
  useEffect(() => {
    if (sketchMode) redrawSketch();
  }, [sketchMode, view, strokes, csize, redrawSketch]);

  const exitSketch = useCallback(() => {
    setSketchMode(false);
    setStrokes([]);
    draftRef.current = null;
    drawingRef.current = false;
    setTool("pen");
    setSketchError(null);
  }, []);

  const toggleSketch = useCallback(() => {
    setSketchMode((on) => {
      if (on) {
        // Turning off IS the cancel path — drop the ephemeral ink (R-223).
        setStrokes([]);
        draftRef.current = null;
        setTool("pen");
        setSketchError(null);
      }
      return !on;
    });
  }, []);

  const eraseAt = useCallback((world: Point) => {
    const r = ERASE_RADIUS / (latestViewRef.current.zoom || 1);
    setStrokes((prev) =>
      prev.filter((s) => !s.some((p) => Math.hypot(p.x - world.x, p.y - world.y) <= r)),
    );
  }, []);

  const onSketchDown = useCallback((e: React.PointerEvent) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    e.preventDefault();
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    setSketchError(null);
    drawingRef.current = true;
    const world = screenToWorld(e.clientX, e.clientY, rect, latestViewRef.current);
    if (toolRef.current === "eraser") {
      eraseAt(world);
      return;
    }
    draftRef.current = [world];
    redrawSketch();
  }, [eraseAt, redrawSketch]);

  const onSketchMove = useCallback((e: React.PointerEvent) => {
    if (!drawingRef.current) return;
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const world = screenToWorld(e.clientX, e.clientY, rect, latestViewRef.current);
    if (toolRef.current === "eraser") {
      eraseAt(world);
      return;
    }
    if (draftRef.current) {
      draftRef.current.push(world);
      redrawSketch(); // imperative — avoids a React render per pointermove
    }
  }, [eraseAt, redrawSketch]);

  const onSketchUp = useCallback((e: React.PointerEvent) => {
    (e.currentTarget as Element).releasePointerCapture?.(e.pointerId);
    drawingRef.current = false;
    const d = draftRef.current;
    draftRef.current = null;
    if (d && d.length > 0) setStrokes((prev) => [...prev, d]);
  }, []);

  // Offscreen raster for the snap: an image sized to the padded bbox, filled with
  // the app's charcoal FIRST (so the model sees strokes-on-charcoal like the real
  // UI, not transparent), then the ink drawn on top at 1:1 world→px.
  const rasterizeSketch = (list: Stroke[], bounds: Bounds): Promise<Blob | null> => {
    // Stage-2b backlog: clamp the offscreen raster to ~2048px/side — a sketch
    // spanning a huge world-space bbox is downscaled (scale < 1) rather than
    // allocating an oversized canvas; a normal-sized sketch is unaffected (scale === 1).
    const scale = rasterScale(bounds);
    const w = Math.max(1, Math.ceil(bounds.width * scale));
    const h = Math.max(1, Math.ceil(bounds.height * scale));
    const off = document.createElement("canvas");
    off.width = w;
    off.height = h;
    const ctx = off.getContext("2d");
    if (!ctx) return Promise.resolve(null);
    const { ink, bg } = readSketchColors();
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = ink;
    ctx.lineWidth = 2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    for (const s of list) {
      if (s.length === 0) continue;
      ctx.beginPath();
      s.forEach((p, i) => {
        const x = (p.x - bounds.minX) * scale;
        const y = (p.y - bounds.minY) * scale;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      if (s.length === 1) {
        ctx.lineTo((s[0].x - bounds.minX) * scale + 0.1, (s[0].y - bounds.minY) * scale + 0.1);
      }
      ctx.stroke();
    }
    return new Promise((resolve) => off.toBlob((b) => resolve(b), "image/png"));
  };

  const doSnap = useCallback(async () => {
    const bounds = strokeBounds(strokesRef.current, SNAP_PAD);
    if (!bounds || snapping) return;
    setSnapping(true);
    setSketchError(null);
    try {
      const blob = await rasterizeSketch(strokesRef.current, bounds);
      if (!blob) throw new Error("Could not rasterize the sketch.");
      const file = new File([blob], "sketch.png", { type: "image/png" });
      // The EXISTING image path — prompt "" + the sketch HINT — feeds the same
      // proposal loop a file upload uses. On a non-vision provider it refuses
      // honestly (422) instead of degrading to a template.
      const result = await api.generateModuleFromFile(file, "", activePageId, SKETCH_HINT);
      const mods = result.modules?.length ? result.modules : result.module ? [result.module] : [];
      if (result.question || mods.length === 0) {
        // A clarifying question OR an empty result means the snap produced nothing
        // to place. Surface it and KEEP the ink — exitSketch would wipe the strokes,
        // silently destroying the user's drawing with no way to retry/adjust.
        setSketchError(
          result.question ?? "The model couldn't read this sketch — add labels and try again.",
        );
        return; // strokes persist; overlay stays open (finally still clears `snapping`)
      }
      onSketchModules?.(mods);
      exitSketch(); // R-223: sketch consumed on success → clear ink + leave mode
    } catch (err) {
      const msg =
        err instanceof ApiError && err.refusal
          ? err.refusal
          : err instanceof Error
            ? err.message
            : "Couldn't snap the sketch.";
      setSketchError(msg);
    } finally {
      setSnapping(false);
    }
  }, [snapping, activePageId, onSketchModules, exitSketch]);

  // Keyboard: `s` toggles sketch (not while typing / with a modifier); Escape
  // cancels an active sketch. Registered on window so it works anywhere on canvas.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const el = e.target as HTMLElement | null;
      const typing = !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
      if (typing) return;
      if (e.key.toLowerCase() === "s") { e.preventDefault(); toggleSketch(); }
      else if (e.key === "Escape" && sketchModeRef.current) { e.preventDefault(); exitSketch(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggleSketch, exitSketch]);

  const canSnap = strokeBounds(strokes, SNAP_PAD) !== null;

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
        {/* R-502/R-504: portal tiles for child pages — a world-coord layer BELOW
            modules (rendered first → modules paint on top; a module drag wins any
            overlap). R-1305: a matte, dashed "place you can enter", distinct from a
            solid module card. R-1306: each tile is focusable + Enter/Space enters. */}
        {childPages && childPages.length > 0 && (
          <div style={{ pointerEvents: "auto" }} className="relative">
            {childPages.map((page, i) => {
              const dragging = portalDrag?.id === page.id;
              const pos = dragging ? portalDrag : portalPosition(page, i);
              const count = childCounts?.[page.id] ?? 0;
              return (
                <div
                  key={page.id}
                  role="button"
                  tabIndex={0}
                  aria-label={`Enter ${page.name}, ${count} ${count === 1 ? "tool" : "tools"}`}
                  title={`Enter ${page.name}`}
                  onPointerDown={(e) => startPortalDrag(e, page.id, portalPosition(page, i))}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onEnterPortal?.(page.id);
                    }
                  }}
                  className={`portal-tile group absolute flex flex-col justify-between select-none rounded-xl border border-dashed p-3 backdrop-blur-sm bg-[var(--surface-elevated)]/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] transition ${
                    dragging
                      ? "border-[var(--accent)] cursor-grabbing shadow-lg"
                      : "border-[var(--border)] cursor-pointer hover:border-[var(--accent)]"
                  }`}
                  style={{ left: pos.x, top: pos.y, width: PORTAL_W, height: PORTAL_H }}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="grid place-items-center w-8 h-8 shrink-0 rounded-lg bg-[var(--surface)] text-[var(--accent)]">
                      <Icon name={resolveIconName(page.icon, page.name)} size={18} />
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium text-[var(--foreground)]">
                        {page.name}
                      </span>
                      <span className="block text-[11px] text-[var(--muted)]">
                        {count} {count === 1 ? "tool" : "tools"}
                      </span>
                    </span>
                  </div>
                  <div className="flex items-center justify-between text-[10px] uppercase tracking-wide text-[var(--muted)]">
                    <span aria-hidden>Page</span>
                    <span className="flex items-center gap-0.5 normal-case tracking-normal text-[11px] text-[var(--muted)] group-hover:text-[var(--accent)] group-focus-visible:text-[var(--accent)] transition">
                      Enter <Icon name="chevronRight" size={12} />
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}

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

      {/* R-221: the sketch overlay sits above modules and controls; while active
          it captures every pointer, suspending pan/drag/module interaction. */}
      {sketchMode && (
        <canvas
          ref={overlayRef}
          className="absolute inset-0 z-[15]"
          style={{ touchAction: "none", cursor: tool === "eraser" ? "cell" : "crosshair" }}
          onPointerDown={onSketchDown}
          onPointerMove={onSketchMove}
          onPointerUp={onSketchUp}
          onPointerCancel={onSketchUp}
        />
      )}

      {sketchMode && (
        <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 flex items-center gap-1 rounded-full bg-[var(--surface)]/95 backdrop-blur px-1.5 py-1 border border-[var(--border)] shadow-lg text-xs">
          <button
            type="button"
            onClick={() => setTool("pen")}
            aria-pressed={tool === "pen"}
            title="Pen"
            className={`flex items-center gap-1 rounded-full px-2 py-1 transition ${tool === "pen" ? "bg-[var(--surface-elevated)] text-[var(--foreground)]" : "text-[var(--muted)] hover:text-[var(--foreground)]"}`}
          >
            <Icon name="pen" size={13} /> Pen
          </button>
          <button
            type="button"
            onClick={() => setTool("eraser")}
            aria-pressed={tool === "eraser"}
            title="Eraser"
            className={`rounded-full px-2 py-1 transition ${tool === "eraser" ? "bg-[var(--surface-elevated)] text-[var(--foreground)]" : "text-[var(--muted)] hover:text-[var(--foreground)]"}`}
          >
            Eraser
          </button>
          <button
            type="button"
            onClick={() => { setStrokes([]); draftRef.current = null; setSketchError(null); }}
            disabled={!canSnap}
            title="Clear the sketch"
            className="rounded-full px-2 py-1 text-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-40 transition"
          >
            Clear
          </button>
          <span className="w-px h-4 bg-[var(--border)] mx-0.5" aria-hidden />
          <button
            type="button"
            onClick={doSnap}
            disabled={!canSnap || snapping}
            title="Turn this sketch into tools"
            className="rounded-full bg-[var(--accent)] text-[var(--accent-fg)] px-3 py-1 font-medium disabled:opacity-40 hover:brightness-110 transition"
          >
            {snapping ? "Snapping…" : "Snap to tools"}
          </button>
          <button
            type="button"
            onClick={exitSketch}
            title="Cancel (Esc)"
            className="rounded-full px-2 py-1 text-[var(--muted)] hover:text-[var(--foreground)] transition"
          >
            Cancel
          </button>
        </div>
      )}

      {sketchMode && sketchError && (
        <div className="absolute top-16 left-1/2 -translate-x-1/2 z-20 max-w-[min(420px,90vw)] rounded-lg border border-[var(--danger)] bg-[var(--surface)] px-3 py-1.5 text-xs text-[var(--danger)] shadow">
          {sketchError}
        </div>
      )}

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
        <span className="w-px h-4 bg-[var(--border)]" aria-hidden />
        {/* R-221: Sketch toggle (keyboard `s`). Turns on the world-space drawing overlay. */}
        <button type="button" onClick={toggleSketch} title="Sketch (s)" aria-label="Toggle sketch mode" aria-pressed={sketchMode}
          className={`transition w-6 h-6 grid place-items-center rounded ${sketchMode ? "text-[var(--accent)]" : "hover:text-[var(--foreground)]"}`}>
          <Icon name="pen" size={13} />
        </button>
      </div>

      {draggingModule && (
        <div className="pointer-events-none absolute inset-0" />
      )}
    </div>
  );
}
