import type { Component, ModuleConfig } from "./types";

/** A one-line summary for a collapsed module (design doc II.2.1). */
export function deriveSummary(
  config: ModuleConfig,
  state: Record<string, unknown>,
): string {
  const byId = (id: string | null | undefined) =>
    config.components.find((c) => c.id === id);

  const target =
    byId(config.summary_component_id) ?? config.components[0] ?? null;

  if (!target) return "Empty module";
  return summarizeComponent(target, state);
}

function summarizeComponent(
  c: Component,
  state: Record<string, unknown>,
): string {
  const raw = state[c.id];
  switch (c.type) {
    case "progress_bar": {
      const source = c.bound_to ? state[c.bound_to] : raw;
      const pct = Math.round(((Number(source) || 0) / (c.max || 1)) * 100);
      return `${c.label}: ${Math.max(0, Math.min(100, pct))}%`;
    }
    case "number_input":
      return `${c.label}: ${raw ?? 0}${c.unit ? ` ${c.unit}` : ""}`;
    case "slider":
      return `${c.label}: ${raw ?? c.min}${c.unit ? ` ${c.unit}` : ""}`;
    case "checkbox":
      return `${c.label}: ${raw ? "✓" : "—"}`;
    case "list": {
      const n = Array.isArray(raw) ? raw.length : 0;
      return `${n} ${c.item_label.toLowerCase()}${n === 1 ? "" : "s"}`;
    }
    case "text_input":
      return raw ? String(raw) : c.label;
    case "metric":
      return `${c.label}: …`;
    case "rating":
      return `${c.label}: ${Number(raw) || 0}★`;
    case "tags": {
      const n = Array.isArray(raw) ? raw.length : 0;
      return `${n} tag${n === 1 ? "" : "s"}`;
    }
    case "kpi":
      return `${c.label}: ${raw ?? 0}${c.unit ? ` ${c.unit}` : ""}`;
    case "date":
      return raw ? `${c.label}: ${raw}` : c.label;
    case "table": {
      const n = Array.isArray(raw) ? raw.length : 0;
      return `${n} row${n === 1 ? "" : "s"}`;
    }
    case "calendar": {
      const n = Array.isArray(raw) ? raw.length : 0;
      return `${n} day${n === 1 ? "" : "s"} marked`;
    }
    case "chart": {
      const n = Array.isArray(raw) ? raw.length : 0;
      return `${c.label}: ${n} point${n === 1 ? "" : "s"}`;
    }
    case "dropdown":
    case "choice_chips":
    case "color":
      return raw ? `${c.label}: ${raw}` : c.label;
    case "sparkline": {
      const arr = Array.isArray(raw) ? raw : [];
      return `${c.label}: ${arr.length ? arr[arr.length - 1] : "—"}`;
    }
    case "ring": {
      const src = c.bound_to ? state[c.bound_to] : raw;
      const pct = Math.round(((Number(src) || 0) / (c.max || 1)) * 100);
      return `${c.label}: ${Math.max(0, Math.min(100, pct))}%`;
    }
    case "timeline": {
      const n = Array.isArray(raw) ? raw.length : 0;
      return `${n} event${n === 1 ? "" : "s"}`;
    }
    case "button":
      return c.label;
    case "section":
      return c.label;
    case "divider":
      return "—";
    case "kanban": {
      const board = raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, string[]>) : {};
      const n = Object.values(board).reduce((s, arr) => s + (Array.isArray(arr) ? arr.length : 0), 0);
      return `${n} card${n === 1 ? "" : "s"}`;
    }
    case "heatmap": {
      const n = raw && typeof raw === "object" ? Object.values(raw as Record<string, number>).filter((v) => v > 0).length : 0;
      return `${n} day${n === 1 ? "" : "s"}`;
    }
    case "gauge":
      return `${c.label}: ${raw ?? 0}${c.unit ? ` ${c.unit}` : ""}`;
    case "checklist": {
      const items = Array.isArray(raw) ? (raw as { done: boolean }[]) : [];
      const done = items.filter((i) => i.done).length;
      return `${c.label}: ${done}/${items.length}`;
    }
    case "gallery": {
      const n = Array.isArray(raw) ? raw.length : 0;
      return `${n} image${n === 1 ? "" : "s"}`;
    }
    case "note":
      return raw ? String(raw).slice(0, 40) : c.label;
  }
}
