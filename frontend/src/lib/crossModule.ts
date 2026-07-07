import type { StoredModule } from "./types";

// Cross-module value resolution, extracted verbatim from Canvas.tsx so the
// shared surface can reuse the one implementation (DESIGN-sharing §4c). It is
// page-scoped by construction: resolution runs over whatever module array it is
// handed, so an off-page `source_module_id` simply resolves to undefined and the
// component falls back to its saved state — no cross-page leak (§7.7).

export function computeMetric(
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

export function crossModuleValues(modules: StoredModule[], module: StoredModule): Record<string, number> {
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
