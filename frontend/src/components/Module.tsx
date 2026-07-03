"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Component, ModuleConfig, StoredModule } from "@/lib/types";
import { runAssembly } from "@/lib/assembly";
import { deriveSummary } from "@/lib/summary";
import { resolveAccent, resolveIconName } from "@/lib/theme";
import { Icon } from "./Icon";
import { CheckboxField } from "./primitives/CheckboxField";
import { ListFieldComponent } from "./primitives/ListFieldComponent";
import { MetricField } from "./primitives/MetricField";
import { NumberInputField } from "./primitives/NumberInputField";
import { ProgressBarField } from "./primitives/ProgressBarField";
import { SliderField } from "./primitives/SliderField";
import { TextInputField } from "./primitives/TextInputField";
import { RatingField } from "./primitives/RatingField";
import { TagsField } from "./primitives/TagsField";
import { KpiField } from "./primitives/KpiField";
import { DateField } from "./primitives/DateField";
import { TableField } from "./primitives/TableField";
import { CalendarField } from "./primitives/CalendarField";
import { ChartField } from "./primitives/ChartField";
import { DropdownField } from "./primitives/DropdownField";
import { ChoiceChipsField } from "./primitives/ChoiceChipsField";
import { ColorPickerField } from "./primitives/ColorPickerField";
import { SparklineField } from "./primitives/SparklineField";
import { RingField } from "./primitives/RingField";
import { TimelineField } from "./primitives/TimelineField";
import { ButtonField } from "./primitives/ButtonField";
import { KanbanField } from "./primitives/KanbanField";
import { HeatmapField } from "./primitives/HeatmapField";
import { GaugeField } from "./primitives/GaugeField";
import { ChecklistField } from "./primitives/ChecklistField";
import { GalleryField } from "./primitives/GalleryField";
import { NoteField } from "./primitives/NoteField";
import { TrackerField } from "./primitives/TrackerField";

// useLayoutEffect on the client (no SSR warning) so the build's initial hidden
// state is set before paint — no flash of the finished card.
const useIsoLayoutEffect = typeof window !== "undefined" ? useLayoutEffect : useEffect;

// In a 2-column module these span the full width rather than sit in one cell.
const WIDE_TYPES = new Set<string>([
  "section", "divider", "table", "chart", "calendar", "kanban", "heatmap", "timeline", "gallery", "note", "tracker",
]);

interface Props {
  module: StoredModule;
  crossModuleValues: Record<string, number>;
  selected: boolean;
  // Preview variant bubbles edits in-memory to its host; canvas/detail persist
  // through the single saver via onCommit.
  onChange?: (updated: StoredModule) => void;
  onCommit?: (id: string, config: ModuleConfig, delay?: number) => void;
  // R-1102: the card's ✕ is undoable (archive), not a hard delete.
  onArchive: (id: string) => void;
  onUndo: (id: string) => void;
  onSelectForRefine: (id: string) => void;
  onSelect: (id: string) => void;
  onEdit?: (id: string) => void;
  onDragStart: (e: React.PointerEvent, moduleId: string) => void;
  onResizeStart: (e: React.PointerEvent, moduleId: string) => void;
  onExpand?: (id: string) => void;
  variant?: "canvas" | "detail" | "preview";
  index?: number;
  onMeasure?: (id: string, height: number) => void;
}

export function Module({
  module, crossModuleValues, selected,
  onChange, onCommit, onArchive, onUndo, onSelectForRefine, onSelect, onEdit, onDragStart, onResizeStart,
  onExpand, variant = "canvas", index = 0, onMeasure,
}: Props) {
  const isCanvas = variant === "canvas";
  const preview = variant === "preview";
  // Single source of truth: render straight from module.config.state. The parent
  // updates it optimistically on every commit (R-601), so there is no local
  // mirror to fall out of sync and revert keystrokes (R-602).
  const state = module.config.state ?? {};
  const [collapsed, setCollapsed] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  // Report the real rendered height up to the canvas so fit/minimap can frame
  // content-sized cards correctly (their layout.height is 0).
  useEffect(() => {
    if (!isCanvas || !onMeasure) return;
    const el = rootRef.current;
    if (!el) return;
    const report = () => onMeasure(module.id, el.offsetHeight);
    report();
    const ro = new ResizeObserver(report);
    ro.observe(el);
    return () => ro.disconnect();
  }, [isCanvas, onMeasure, module.id]);

  // Signature "module build" assembly motion — runs when a canvas tile mounts
  // (page load, page switch, or generation). Reduced motion → final state instantly.
  useIsoLayoutEffect(() => {
    if (!isCanvas || !rootRef.current) return;
    const m = document.documentElement.dataset.motion;
    const reduced =
      m === "reduced" ||
      (m !== "full" && typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
    if (reduced) return; // accessibility: no animation, the finished card is already correct
    return runAssembly(rootRef.current, index);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setField = useCallback(
    (id: string, value: unknown) => {
      const base = module.config.state ?? {};
      let next: Record<string, unknown> = { ...base, [id]: value };
      // Automations: "when this field … then increment another" (visible + undoable).
      for (const r of module.config.automations ?? []) {
        if (r.when_id !== id || r.then !== "increment" || !r.then_id) continue;
        const fired = (r.when === "checked" && value === true) || r.when === "changes";
        if (fired) next = { ...next, [r.then_id]: (Number(next[r.then_id]) || 0) + (r.then_value ?? 1) };
      }
      const nextConfig: ModuleConfig = { ...module.config, state: next };
      // Previews aren't persisted — bubble the edited config to the host in memory.
      // Canvas/detail commit through the single saver (optimistic parent update
      // now, PATCH debounced after).
      if (preview) onChange?.({ ...module, config: nextConfig });
      else onCommit?.(module.id, nextConfig);
    },
    [module, preview, onChange, onCommit],
  );

  const renderComponent = (c: Component) => {
    switch (c.type) {
      case "text_input":
        return <TextInputField key={c.id} spec={c} value={(state[c.id] as string) ?? ""} onChange={(v) => setField(c.id, v)} />;
      case "number_input":
        return <NumberInputField key={c.id} spec={c} value={(state[c.id] as number | "") ?? ""} onChange={(v) => setField(c.id, v)} />;
      case "checkbox":
        return <CheckboxField key={c.id} spec={c} value={Boolean(state[c.id])} onChange={(v) => setField(c.id, v)} />;
      case "slider":
        return <SliderField key={c.id} spec={c} value={(state[c.id] as number) ?? c.min} onChange={(v) => setField(c.id, v)} />;
      case "progress_bar": {
        const sourceVal =
          c.source_module_id && crossModuleValues[c.id] !== undefined
            ? crossModuleValues[c.id]
            : c.bound_to
              ? (state[c.bound_to] as number) ?? 0
              : (state[c.id] as number) ?? 0;
        return <ProgressBarField key={c.id} spec={c} value={sourceVal} />;
      }
      case "list":
        return <ListFieldComponent key={c.id} spec={c} value={(state[c.id] as string[]) ?? []} onChange={(v) => setField(c.id, v)} />;
      case "metric":
        return <MetricField key={c.id} spec={c} value={crossModuleValues[c.id] ?? 0} />;
      case "rating":
        return <RatingField key={c.id} spec={c} value={(state[c.id] as number) ?? 0} onChange={(v) => setField(c.id, v)} />;
      case "tags":
        return <TagsField key={c.id} spec={c} value={(state[c.id] as string[]) ?? []} onChange={(v) => setField(c.id, v)} />;
      case "kpi":
        return <KpiField key={c.id} spec={c} value={(state[c.id] as number | "") ?? ""} onChange={(v) => setField(c.id, v)} />;
      case "date":
        return <DateField key={c.id} spec={c} value={(state[c.id] as string) ?? ""} onChange={(v) => setField(c.id, v)} />;
      case "table":
        return <TableField key={c.id} spec={c} value={(state[c.id] as string[][]) ?? []} onChange={(v) => setField(c.id, v)} />;
      case "calendar":
        return <CalendarField key={c.id} spec={c} value={(state[c.id] as string[]) ?? []} onChange={(v) => setField(c.id, v)} />;
      case "chart":
        return <ChartField key={c.id} spec={c} value={(state[c.id] as { label: string; value: number }[]) ?? []} onChange={(v) => setField(c.id, v)} />;
      case "dropdown":
        return <DropdownField key={c.id} spec={c} value={(state[c.id] as string) ?? ""} onChange={(v) => setField(c.id, v)} />;
      case "choice_chips":
        return <ChoiceChipsField key={c.id} spec={c} value={(state[c.id] as string) ?? ""} onChange={(v) => setField(c.id, v)} />;
      case "color":
        return <ColorPickerField key={c.id} spec={c} value={(state[c.id] as string) ?? ""} onChange={(v) => setField(c.id, v)} />;
      case "sparkline":
        return <SparklineField key={c.id} spec={c} value={(state[c.id] as number[]) ?? []} onChange={(v) => setField(c.id, v)} />;
      case "ring": {
        const rv = c.bound_to ? (state[c.bound_to] as number) ?? 0 : (state[c.id] as number) ?? 0;
        return <RingField key={c.id} spec={c} value={rv} onChange={c.bound_to ? undefined : (v) => setField(c.id, v)} />;
      }
      case "timeline":
        return <TimelineField key={c.id} spec={c} value={(state[c.id] as { date: string; label: string }[]) ?? []} onChange={(v) => setField(c.id, v)} />;
      case "button": {
        // With no explicit target, increment/add_item act on the button's own
        // state so a freshly-added Button is functional out of the box.
        const tgt = c.target || c.id;
        const act = () => {
          if (c.action === "increment") {
            setField(tgt, (Number(state[tgt]) || 0) + 1);
          } else if (c.action === "add_item") {
            const cur = Array.isArray(state[tgt]) ? (state[tgt] as string[]) : [];
            setField(tgt, [...cur, "New item"]);
          }
        };
        const count =
          c.action === "increment" ? (Number(state[tgt]) || 0)
          : c.action === "add_item" ? (Array.isArray(state[tgt]) ? (state[tgt] as string[]).length : 0)
          : undefined;
        return <ButtonField key={c.id} spec={c} onAction={act} count={count} />;
      }
      case "section":
        return (
          <div key={c.id} className="pt-1">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-[var(--muted)] border-b border-[var(--border)] pb-1">{c.label}</div>
          </div>
        );
      case "divider":
        return <div key={c.id} className="border-t border-[var(--border)] my-0.5" />;
      case "kanban":
        return <KanbanField key={c.id} spec={c} value={(state[c.id] as Record<string, string[]>) ?? {}} onChange={(v) => setField(c.id, v)} />;
      case "heatmap":
        return <HeatmapField key={c.id} spec={c} value={(state[c.id] as Record<string, number>) ?? {}} onChange={(v) => setField(c.id, v)} />;
      case "gauge":
        return <GaugeField key={c.id} spec={c} value={(state[c.id] as number) ?? c.min} onChange={(v) => setField(c.id, v)} />;
      case "checklist":
        return <ChecklistField key={c.id} spec={c} value={(state[c.id] as { text: string; done: boolean }[]) ?? []} onChange={(v) => setField(c.id, v)} />;
      case "gallery":
        return <GalleryField key={c.id} spec={c} value={(state[c.id] as string[]) ?? []} onChange={(v) => setField(c.id, v)} />;
      case "note":
        return <NoteField key={c.id} spec={c} value={(state[c.id] as string) ?? ""} onChange={(v) => setField(c.id, v)} />;
      case "tracker":
        return <TrackerField key={c.id} spec={c} value={(state[c.id] as { rows: { name: string; done: string[] }[] }) ?? { rows: [] }} onChange={(v) => setField(c.id, v)} />;
    }
  };

  const { layout } = module.config;
  const iconBtn =
    "text-xs text-[var(--muted)] hover:text-[var(--foreground)] transition px-1.5 h-6 flex items-center justify-center rounded";

  const components = module.config.components;
  const title = module.config.title;
  const theme = resolveAccent(module.config.accent, module.config.title, module.config.theme_opt_in ?? false);
  const iconName = resolveIconName(module.config.icon, module.config.title);
  const densityVars =
    module.config.density === "compact"
      ? { ["--mod-pad" as string]: "0.6rem", ["--mod-gap" as string]: "0.55rem" }
      : {};
  // Constrained design layer carried from a screenshot capture (closed-enum tokens,
  // no raw CSS). Available as CSS vars; the card radius is applied here directly.
  const RADIUS: Record<string, string> = { sharp: "8px", rounded: "16px", pill: "28px" };
  const TYPE_SCALE: Record<string, string> = { compact: "0.92", regular: "1", large: "1.08" };
  const designVars: Record<string, string> = {};
  if (module.config.radius && RADIUS[module.config.radius]) designVars["--mod-radius"] = RADIUS[module.config.radius];
  if (module.config.type_scale && TYPE_SCALE[module.config.type_scale]) designVars["--mod-type-scale"] = TYPE_SCALE[module.config.type_scale];
  const radiusOverride = module.config.radius ? { borderRadius: "var(--mod-radius)" } : {};
  const twoCol = module.config.columns === 2;

  // Automations: "when a field goes over/under a value, flag another field red."
  const flagged = new Set<string>();
  for (const r of module.config.automations ?? []) {
    if (r.then !== "flag" || !r.then_id) continue;
    const v = Number(state[r.when_id]);
    if (Number.isNaN(v)) continue;
    if (r.when === "over" && v > (r.when_value ?? 0)) flagged.add(r.then_id);
    if (r.when === "under" && v < (r.when_value ?? 0)) flagged.add(r.then_id);
  }

  return (
    <div
      ref={rootRef}
      onMouseDown={isCanvas ? () => onSelect(module.id) : undefined}
      className={`rounded-2xl border bg-[var(--surface)] flex flex-col ${
        isCanvas ? "absolute shadow-lg shadow-black/30 transition-[transform,box-shadow] duration-200 hover:shadow-xl hover:shadow-black/40 hover:-translate-y-0.5 will-change-transform" : "relative w-full shadow-none"
      }`}
      style={!isCanvas ? ({
        ["--accent" as string]: theme.accent,
        ["--accent-fg" as string]: theme.accentFg,
        borderColor: "var(--border)",
        ...densityVars,
        ...designVars,
        ...radiusOverride,
      } as React.CSSProperties) : ({
        left: layout.x,
        top: layout.y,
        width: layout.width,
        // Cards size to their content (no wasted space); a manual resize sets an
        // explicit taller min-height via layout.height when the user wants it.
        minHeight: collapsed || !layout.height ? undefined : layout.height,
        ["--accent" as string]: theme.accent,
        ["--accent-fg" as string]: theme.accentFg,
        borderColor: selected ? "var(--accent)" : "var(--border)",
        outline: selected ? "2px solid color-mix(in srgb, var(--accent) 55%, transparent)" : "none",
        outlineOffset: "2px",
        ...densityVars,
        ...designVars,
        ...radiusOverride,
      } as React.CSSProperties)}
    >
      {isCanvas && (
        <>
          {/* Beat 2 — the border traces itself. */}
          <svg data-assembly="border-svg" className="pointer-events-none absolute inset-0 z-20 opacity-0" preserveAspectRatio="none" aria-hidden>
            <rect data-assembly="border" fill="none" stroke="var(--accent)" strokeWidth="1.5" rx="16" ry="16" />
          </svg>
          {/* Beat 4 — a light band sweeps across. */}
          <div className="pointer-events-none absolute inset-0 z-20 overflow-hidden rounded-2xl" aria-hidden>
            <div data-assembly="scan" className="absolute inset-y-0 left-0 w-1/2 opacity-0"
              style={{ background: "linear-gradient(100deg, transparent 20%, color-mix(in srgb, var(--white-matte) 28%, transparent) 50%, transparent 80%)" }} />
          </div>
        </>
      )}
      {isCanvas && (
        <div
          className="absolute bottom-1 right-1 w-4 h-4 cursor-se-resize opacity-0 hover:opacity-100 transition-opacity flex items-end justify-end"
          style={{ touchAction: "none" }}
          onPointerDown={(e) => onResizeStart(e, module.id)}
          aria-label="Resize module"
          title="Resize"
        >
          <svg width="8" height="8" viewBox="0 0 8 8" fill="none" aria-hidden>
            <circle cx="6" cy="6" r="1" fill="currentColor" className="text-[var(--muted)]" />
            <circle cx="3" cy="6" r="1" fill="currentColor" className="text-[var(--muted)]" />
            <circle cx="6" cy="3" r="1" fill="currentColor" className="text-[var(--muted)]" />
          </svg>
        </div>
      )}

      <div
        className={`flex items-center gap-1.5 px-3 py-3 border-b border-[var(--border)] ${isCanvas ? "cursor-grab active:cursor-grabbing" : ""}`}
        onPointerDown={!isCanvas ? undefined : (e) => {
          if ((e.target as HTMLElement).closest("button,input,select,textarea,a")) return;
          onDragStart(e, module.id);
        }}
        onDoubleClick={isCanvas && onExpand ? (e) => {
          if ((e.target as HTMLElement).closest("button,input,select,textarea,a")) return;
          onExpand(module.id);
        } : undefined}
      >
        {isCanvas && (
          <button type="button" onClick={() => setCollapsed((v) => !v)} className={iconBtn}
            aria-label={collapsed ? "Expand" : "Collapse"}>
            <span className="inline-block transition-transform" style={{ transform: collapsed ? "rotate(-90deg)" : "none" }}>
              <Icon name="chevronDown" size={14} />
            </span>
          </button>
        )}

        <span className="shrink-0 grid place-items-center w-6 h-6 rounded-md leading-none select-none"
          style={{ background: "color-mix(in srgb, var(--accent) 20%, transparent)", color: "var(--accent)" }} aria-hidden>
          <Icon name={iconName} size={15} />
        </span>

        <h3 data-assembly="label" className="flex-1 min-w-0 text-sm font-semibold tracking-tight select-none truncate" title={title}>
          {title}
        </h3>

        {!preview && (
          <>
            <button type="button" onClick={() => onUndo(module.id)} className={iconBtn}
              aria-label="Undo last change" title="Undo last change"><Icon name="undo" size={14} /></button>
            <button type="button" onClick={() => onSelectForRefine(module.id)} className={iconBtn}
              aria-label="Refine with AI" title="Refine with AI"><Icon name="sparkles" size={14} /></button>
            {isCanvas && onExpand && (
              <button type="button" onClick={() => onExpand(module.id)} className={iconBtn}
                aria-label="Expand to full page" title="Open full page"><Icon name="maximize" size={13} /></button>
            )}
            <button type="button" onClick={() => (onEdit ?? onSelect)(module.id)} className={iconBtn}
              aria-label="Edit module" title="Edit in inspector"><Icon name="pen" size={14} /></button>
            <button type="button" onClick={() => onArchive(module.id)} className={iconBtn}
              aria-label="Archive" title="Archive (restore from Archived)"><Icon name="archive" size={14} /></button>
          </>
        )}
      </div>

      {collapsed ? (
        <div className="px-4 py-3 text-xs text-[var(--muted)] font-mono">
          {deriveSummary(module.config, state)}
        </div>
      ) : (
        <div data-assembly="body" className={twoCol
          ? "grid grid-cols-2 gap-[var(--mod-gap)] p-[var(--mod-pad)] items-start"
          : "flex flex-col p-[var(--mod-pad)] gap-[var(--mod-gap)]"}>
          {components.map((c) => {
            const inner = flagged.has(c.id) ? (
              <div className="rounded-lg ring-1 ring-[var(--danger)] bg-[var(--danger)]/5 p-2">
                <div className="flex items-center gap-1 text-[10px] text-[var(--danger)] mb-1">⚠ flagged</div>
                {renderComponent(c)}
              </div>
            ) : renderComponent(c);
            const wide = c.span === "full" || (c.span !== "half" && WIDE_TYPES.has(c.type));
            return (
              <div key={c.id} className={`min-w-0 ${twoCol && wide ? "col-span-2" : ""}`}>
                {inner}
              </div>
            );
          })}
          {components.length === 0 && (
            <p className="text-xs text-[var(--muted)] italic col-span-2">No fields yet — open the inspector to add some.</p>
          )}
        </div>
      )}
    </div>
  );
}
