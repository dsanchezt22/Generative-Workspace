import { describe, expect, it } from "vitest";
import type { Component, ModuleConfig, StoredModule } from "./types";
import { computeMetric, crossModuleValues } from "./crossModule";

// A minimal StoredModule around a components list + state — only the fields
// crossModuleValues/computeMetric read (id, config.components, config.state).
function mod(id: string, components: Component[], state: Record<string, unknown>): StoredModule {
  const config: ModuleConfig = {
    title: id,
    components,
    state,
    layout: { x: 0, y: 0, width: 300, height: 0 },
  };
  return { id, config, created_at: "", updated_at: "", archived: false, rev: 0 };
}

const num = (id: string): Component => ({ id, label: id, type: "number_input" });

describe("computeMetric", () => {
  const mods = [mod("a", [num("v")], { v: 10 }), mod("b", [num("v")], { v: 20 }), mod("c", [num("v")], { v: 30 })];

  it("sums / counts / averages / maxes / mins the source across modules", () => {
    expect(computeMetric(mods, "sum", "v", "none")).toBe(60);
    expect(computeMetric(mods, "count", "v", "none")).toBe(3);
    expect(computeMetric(mods, "avg", "v", "none")).toBe(20);
    expect(computeMetric(mods, "max", "v", "none")).toBe(30);
    expect(computeMetric(mods, "min", "v", "none")).toBe(10);
  });

  it("excludes the excludeId module from the aggregate", () => {
    expect(computeMetric(mods, "sum", "v", "b")).toBe(40); // 10 + 30, b dropped
    expect(computeMetric(mods, "count", "v", "a")).toBe(2);
  });

  it("returns 0 when no numeric source values remain", () => {
    expect(computeMetric([mod("a", [num("v")], {})], "sum", "v", "none")).toBe(0);
    expect(computeMetric(mods, "sum", "v", "z")).toBe(60); // unknown excludeId excludes nothing
  });
});

describe("crossModuleValues", () => {
  it("resolves a metric component over the OTHER modules (self excluded)", () => {
    const self = mod("self", [{ id: "total", label: "Total", type: "metric", formula: "sum", source_component_id: "v" }], { v: 100 });
    const others = [mod("a", [num("v")], { v: 5 }), mod("b", [num("v")], { v: 7 })];
    const values = crossModuleValues([self, ...others], self);
    expect(values.total).toBe(12); // self's own v:100 excluded
  });

  it("omits the key when a progress_bar's source_module_id points at an absent module", () => {
    const m = mod("m", [{ id: "bar", label: "Bar", type: "progress_bar", max: 100, bound_to: "src", source_module_id: "ghost" }], {});
    const values = crossModuleValues([m], m);
    expect("bar" in values).toBe(false); // fallback path: component reads saved state instead
  });

  it("reads a bound value when the source_module_id resolves", () => {
    const src = mod("src", [num("out")], { out: 42 });
    const m = mod("m", [{ id: "bar", label: "Bar", type: "progress_bar", max: 100, bound_to: "out", source_module_id: "src" }], {});
    const values = crossModuleValues([m, src], m);
    expect(values.bar).toBe(42);
  });
});
