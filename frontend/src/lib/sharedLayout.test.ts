import { describe, expect, it } from "vitest";
import type { ModuleLayout } from "./types";
import { normalizeLayout } from "./sharedLayout";

const layout = (x: number, y: number, width = 300, height = 200): ModuleLayout => ({ x, y, width, height });

describe("normalizeLayout", () => {
  it("is safe on an empty set", () => {
    expect(normalizeLayout([])).toEqual({ width: 0, height: 0, boxes: [] });
  });

  it("shifts the top-left module to the origin", () => {
    const { boxes } = normalizeLayout([
      { id: "a", layout: layout(100, 80) },
      { id: "b", layout: layout(500, 380) },
    ]);
    expect(boxes[0]).toEqual({ id: "a", x: 0, y: 0, width: 300 });
    expect(boxes[1]).toEqual({ id: "b", x: 400, y: 300, width: 300 });
  });

  it("normalizes negative owner coordinates to non-negative offsets", () => {
    const { boxes, width, height } = normalizeLayout([
      { id: "a", layout: layout(-200, -100, 300, 200) },
      { id: "b", layout: layout(100, 100, 300, 200) },
    ]);
    expect(boxes.every((b) => b.x >= 0 && b.y >= 0)).toBe(true);
    expect(boxes[0]).toEqual({ id: "a", x: 0, y: 0, width: 300 });
    // bounding box spans from -200..400 (x) and -100..300 (y)
    expect(width).toBe(600);
    expect(height).toBe(400);
  });

  it("sizes the bounding box to cover the widest/tallest extents", () => {
    const { width, height } = normalizeLayout([
      { id: "a", layout: layout(0, 0, 400, 100) },
      { id: "b", layout: layout(0, 300, 200, 500) },
    ]);
    expect(width).toBe(400); // widest right edge
    expect(height).toBe(800); // b bottom edge = 300 + 500
  });
});
