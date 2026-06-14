"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Component, ModuleConfig, StoredModule } from "@/lib/types";
import { api } from "@/lib/api";
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

// In a 2-column module these span the full width rather than sit in one cell.
const WIDE_TYPES = new Set<string>([
  "section", "divider", "table", "chart", "calendar", "kanban", "heatmap", "timeline", "gallery", "note",
]);

interface Props {
  module: StoredModule;
  crossModuleValues: Record<string, number>;
  selected: boolean;
  onChange: (updated: StoredModule) => void;
  onDelete: (id: string) => void;
  onUndo: (id: string) => void;
  onSelectForRefine: (id: string) => void;
  onSelect: (id: string) => void;
  onDragStart: (e: React.PointerEvent, moduleId: string) => void;
  onResizeStart: (e: React.PointerEvent, moduleId: string) => void;
}

export function Module({
  module, crossModuleValues, selected,
  onChange, onDelete, onUndo, onSelectForRefine, onSelect, onDragStart, onResizeStart,
}: Props) {
  const [state, setState] = useState<Record<string, unknown>>(module.config.state ?? {});
  const [collapsed, setCollapsed] = useState(false);
  const persistTimer = useRef<number | null>(null);

  useEffect(() => {
    setState(module.config.state ?? {});
  }, [module.id, module.config.state]);

  const persistConfig = useCallback(
    async (config: ModuleConfig) => {
      try {
        const saved = await api.patchModule(module.id, config);
        onChange(saved);
      } catch (err) {
        console.error("Failed to persist module config", err);
      }
    },
    [module.id, onChange],
  );

  const schedulePersist = useCallback(
    (config: ModuleConfig, delay = 400) => {
      if (persistTimer.current) window.clearTimeout(persistTimer.current);
      persistTimer.current = window.setTimeout(() => void persistConfig(config), delay);
    },
    [persistConfig],
  );

  const setField = useCallback(
    (id: string, value: unknown) => {
      setState((prev) => {
        let next: Record<string, unknown> = { ...prev, [id]: value };
        // Automations: "when this field … then increment another" (visible + undoable).
        for (const r of module.config.automations ?? []) {
          if (r.when_id !== id || r.then !== "increment" || !r.then_id) continue;
          const fired = (r.when === "checked" && value === true) || r.when === "changes";
          if (fired) next = { ...next, [r.then_id]: (Number(next[r.then_id]) || 0) + (r.then_value ?? 1) };
        }
        schedulePersist({ ...module.config, state: next });
        return next;
      });
    },
    [module.config, schedulePersist],
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
        const act = () => {
          if (c.action === "increment" && c.target) {
            setField(c.target, (Number(state[c.target]) || 0) + 1);
          } else if (c.action === "add_item" && c.target) {
            const cur = Array.isArray(state[c.target]) ? (state[c.target] as string[]) : [];
            setField(c.target, [...cur, "New item"]);
          }
        };
        return <ButtonField key={c.id} spec={c} onAction={act} />;
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
    }
  };

  const { layout } = module.config;
  const iconBtn =
    "text-xs text-[var(--muted)] hover:text-[var(--foreground)] transition px-1.5 h-6 flex items-center justify-center rounded";

  const components = module.config.components;
  const title = module.config.title;
  const theme = resolveAccent(module.config.accent, module.config.title);
  const iconName = resolveIconName(module.config.icon, module.config.title);
  const densityVars =
    module.config.density === "compact"
      ? { ["--mod-pad" as string]: "0.6rem", ["--mod-gap" as string]: "0.55rem" }
      : {};
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
      onMouseDown={() => onSelect(module.id)}
      className="absolute rounded-2xl border bg-[var(--surface)] shadow-lg shadow-black/30 flex flex-col animate-pop transition-shadow hover:shadow-xl hover:shadow-black/40"
      style={{
        left: layout.x,
        top: layout.y,
        width: layout.width,
        minHeight: collapsed ? undefined : layout.height,
        ["--accent" as string]: theme.accent,
        ["--accent-fg" as string]: theme.accentFg,
        borderColor: selected
          ? "var(--accent)"
          : "color-mix(in srgb, var(--accent) 28%, var(--border))",
        outline: selected ? "2px solid color-mix(in srgb, var(--accent) 55%, transparent)" : "none",
        outlineOffset: "2px",
        ...densityVars,
      } as React.CSSProperties}
    >
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

      <div
        className="flex items-center gap-1.5 px-3 py-3 border-b border-[var(--border)] cursor-grab active:cursor-grabbing"
        onPointerDown={(e) => {
          if ((e.target as HTMLElement).closest("button,input,select,textarea,a")) return;
          onDragStart(e, module.id);
        }}
      >
        <button type="button" onClick={() => setCollapsed((v) => !v)} className={iconBtn}
          aria-label={collapsed ? "Expand" : "Collapse"}>
          <span className="inline-block transition-transform" style={{ transform: collapsed ? "rotate(-90deg)" : "none" }}>
            <Icon name="chevronDown" size={14} />
          </span>
        </button>

        <span className="shrink-0 grid place-items-center w-6 h-6 rounded-md leading-none select-none"
          style={{ background: "color-mix(in srgb, var(--accent) 20%, transparent)", color: "var(--accent)" }} aria-hidden>
          <Icon name={iconName} size={15} />
        </span>

        <h3 className="flex-1 min-w-0 text-sm font-semibold tracking-tight select-none truncate" title={title}>
          {title}
        </h3>

        <button type="button" onClick={() => onUndo(module.id)} className={iconBtn}
          aria-label="Undo last change" title="Undo last change"><Icon name="undo" size={14} /></button>
        <button type="button" onClick={() => onSelectForRefine(module.id)} className={iconBtn}
          aria-label="Refine with AI" title="Refine with AI"><Icon name="sparkles" size={14} /></button>
        <button type="button" onClick={() => onSelect(module.id)} className={iconBtn}
          aria-label="Edit module" title="Edit in inspector"><Icon name="pen" size={14} /></button>
        <button type="button" onClick={() => onDelete(module.id)} className={`${iconBtn} hover:text-[var(--danger)]`}
          aria-label="Delete module"><Icon name="x" size={14} /></button>
      </div>

      {collapsed ? (
        <div className="px-4 py-3 text-xs text-[var(--muted)] font-mono">
          {deriveSummary(module.config, state)}
        </div>
      ) : (
        <div className={twoCol
          ? "grid grid-cols-2 gap-[var(--mod-gap)] p-[var(--mod-pad)] items-start"
          : "flex flex-col p-[var(--mod-pad)] gap-[var(--mod-gap)]"}>
          {components.map((c) => {
            const inner = flagged.has(c.id) ? (
              <div className="rounded-lg ring-1 ring-[var(--danger)] bg-[var(--danger)]/5 p-2">
                <div className="flex items-center gap-1 text-[10px] text-[var(--danger)] mb-1">⚠ flagged</div>
                {renderComponent(c)}
              </div>
            ) : renderComponent(c);
            return (
              <div key={c.id} className={`min-w-0 ${twoCol && WIDE_TYPES.has(c.type) ? "col-span-2" : ""}`}>
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
