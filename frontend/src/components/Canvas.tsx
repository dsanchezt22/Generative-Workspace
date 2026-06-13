"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { StoredModule } from "@/lib/types";
import { Module } from "./Module";
import { api, ApiError } from "@/lib/api";

function InsightsButton({
  modules,
  activePageId,
  onNewModule,
}: {
  modules: StoredModule[];
  activePageId?: string;
  onNewModule: (m: StoredModule) => void;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const generate = async () => {
    setLoading(true);
    setError(null);
    try {
      const { module } = await api.workspaceInsights(activePageId);
      onNewModule(module);
    } catch (err) {
      const msg =
        err instanceof ApiError && err.refusal
          ? err.refusal
          : err instanceof Error
            ? err.message
            : "Could not generate insights.";
      setError(msg);
      setTimeout(() => setError(null), 4000);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex flex-col items-center gap-1.5">
      {error && (
        <div className="rounded-lg bg-[var(--surface)] border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--danger)] shadow">
          {error}
        </div>
      )}
      <button
        type="button"
        onClick={generate}
        disabled={loading}
        className="rounded-full bg-[var(--surface)]/90 backdrop-blur border border-[var(--border)] px-4 py-1.5 text-xs text-[var(--muted)] hover:text-[var(--foreground)] hover:border-[var(--accent)] transition disabled:opacity-40 shadow font-mono"
        title="Generate a dashboard that aggregates your modules"
      >
        {loading ? "Synthesizing…" : "✦ Workspace insights"}
      </button>
    </div>
  );
}

interface Props {
  modules: StoredModule[];
  onModuleChange: (updated: StoredModule) => void;
  onModuleDelete: (id: string) => void;
  onModuleUndo: (id: string) => void;
  onModuleSelectForRefine: (id: string) => void;
  onNewModule: (m: StoredModule) => void;
  activePageId?: string;
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
  onModuleDelete,
  onModuleUndo,
  onModuleSelectForRefine,
  onNewModule,
  activePageId,
}: Props) {
  const [view, setView] = useState<View>({ x: 0, y: 0, zoom: 1 });
  const [draggingModule, setDraggingModule] = useState<string | null>(null);
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
      (e.currentTarget as Element).setPointerCapture(e.pointerId);
      panRef.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
    },
    [view],
  );

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (moduleDragRef.current) {
      const { moduleId, startClient, startLayout } = moduleDragRef.current;
      const dx = (e.clientX - startClient.x) / viewZoomRef.current;
      const dy = (e.clientY - startClient.y) / viewZoomRef.current;
      const m = latestModulesRef.current.find((mm) => mm.id === moduleId);
      if (!m) return;
      onModuleChange({
        ...m,
        config: { ...m.config, layout: { ...m.config.layout, x: startLayout.x + dx, y: startLayout.y + dy } },
      });
      return;
    }
    if (moduleResizeRef.current) {
      const { moduleId, startClient, startSize } = moduleResizeRef.current;
      const dx = (e.clientX - startClient.x) / viewZoomRef.current;
      const dy = (e.clientY - startClient.y) / viewZoomRef.current;
      const m = latestModulesRef.current.find((mm) => mm.id === moduleId);
      if (!m) return;
      onModuleChange({
        ...m,
        config: {
          ...m.config,
          layout: {
            ...m.config.layout,
            width: Math.max(240, startSize.width + dx),
            height: Math.max(160, startSize.height + dy),
          },
        },
      });
      return;
    }
    if (!panRef.current) return;
    const { x, y, vx, vy } = panRef.current;
    setView((prev) => ({ ...prev, x: vx + (e.clientX - x), y: vy + (e.clientY - y) }));
  }, [onModuleChange]);

  const onPointerUp = useCallback(
    async (e: React.PointerEvent) => {
      (e.currentTarget as Element).releasePointerCapture?.(e.pointerId);
      panRef.current = null;
      if (moduleDragRef.current) {
        const { moduleId } = moduleDragRef.current;
        const m = latestModulesRef.current.find((mm) => mm.id === moduleId);
        moduleDragRef.current = null;
        setDraggingModule(null);
        if (m) {
          try {
            await api.patchModule(m.id, m.config);
          } catch (err) {
            console.error("Failed to persist layout", err);
          }
        }
      }
      if (moduleResizeRef.current) {
        const { moduleId } = moduleResizeRef.current;
        const m = latestModulesRef.current.find((mm) => mm.id === moduleId);
        moduleResizeRef.current = null;
        if (m) {
          try {
            await api.patchModule(m.id, m.config);
          } catch (err) {
            console.error("Failed to persist resize", err);
          }
        }
      }
    },
    [],
  );

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

  const latestModulesRef = useRef(modules);
  useEffect(() => {
    latestModulesRef.current = modules;
  }, [modules]);

  const handleModuleDragStart = useCallback(
    (e: React.PointerEvent, moduleId: string) => {
      const m = latestModulesRef.current.find((mm) => mm.id === moduleId);
      if (!m) return;
      e.stopPropagation();
      moduleDragRef.current = {
        moduleId,
        startClient: { x: e.clientX, y: e.clientY },
        startLayout: { x: m.config.layout.x, y: m.config.layout.y },
      };
      setDraggingModule(moduleId);
      const root = containerRef.current;
      if (root) root.setPointerCapture(e.pointerId);
    },
    [],
  );

  const handleResizeStart = useCallback(
    (e: React.PointerEvent, moduleId: string) => {
      const m = latestModulesRef.current.find((mm) => mm.id === moduleId);
      if (!m) return;
      e.stopPropagation();
      moduleResizeRef.current = {
        moduleId,
        startClient: { x: e.clientX, y: e.clientY },
        startSize: { width: m.config.layout.width, height: m.config.layout.height },
      };
      const root = containerRef.current;
      if (root) root.setPointerCapture(e.pointerId);
    },
    [],
  );

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
          {modules.map((m) => (
            <Module
              key={m.id}
              module={m}
              crossModuleValues={crossModuleValues(modules, m)}
              onChange={onModuleChange}
              onDelete={onModuleDelete}
              onUndo={onModuleUndo}
              onSelectForRefine={onModuleSelectForRefine}
              onDragStart={handleModuleDragStart}
              onResizeStart={handleResizeStart}
            />
          ))}
        </div>
      </div>

      {modules.length >= 2 && (
        <InsightsButton modules={modules} activePageId={activePageId} onNewModule={onNewModule} />
      )}

      <div className="absolute bottom-4 right-4 flex items-center gap-2 rounded-full bg-[var(--surface)]/80 backdrop-blur px-3 py-1.5 border border-[var(--border)] text-xs text-[var(--muted)] font-mono">
        <button
          type="button"
          onClick={() => setView({ x: 0, y: 0, zoom: 1 })}
          className="hover:text-[var(--foreground)] transition"
          aria-label="Reset view"
        >
          reset
        </button>
        <span aria-hidden>·</span>
        <span>{Math.round(view.zoom * 100)}%</span>
      </div>

      {draggingModule && (
        <div className="pointer-events-none absolute inset-0" />
      )}
    </div>
  );
}
