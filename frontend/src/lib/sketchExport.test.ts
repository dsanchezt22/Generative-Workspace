import { describe, expect, it } from "vitest";
import { rasterScale, screenToWorld, strokeBounds, worldToScreen } from "./sketchExport";

describe("strokeBounds (R-221: bbox for the snap raster)", () => {
  it("bounds a multi-stroke sketch across all points", () => {
    const b = strokeBounds(
      [
        [
          { x: 0, y: 0 },
          { x: 10, y: 10 },
        ],
        [
          { x: 5, y: -5 },
          { x: 20, y: 3 },
        ],
      ],
      0,
    );
    expect(b).toEqual({ minX: 0, minY: -5, maxX: 20, maxY: 10, width: 20, height: 15 });
  });

  it("bounds a single point as a zero-size box", () => {
    const b = strokeBounds([[{ x: 4, y: 7 }]], 0);
    expect(b).toEqual({ minX: 4, minY: 7, maxX: 4, maxY: 7, width: 0, height: 0 });
  });

  it("returns null for no strokes (snap disabled)", () => {
    expect(strokeBounds([], 0)).toBeNull();
  });

  it("returns null for strokes with no points (snap disabled)", () => {
    expect(strokeBounds([[], []], 24)).toBeNull();
  });

  it("grows the box by pad on every side", () => {
    const b = strokeBounds([[{ x: 0, y: 0 }]], 24);
    expect(b).toEqual({ minX: -24, minY: -24, maxX: 24, maxY: 24, width: 48, height: 48 });
  });
});

describe("rasterScale (Stage-2b backlog: clamp the offscreen raster to ~2048px/side)", () => {
  it("returns 1 when the longest side is within the cap", () => {
    expect(rasterScale({ minX: 0, minY: 0, maxX: 500, maxY: 300, width: 500, height: 300 })).toBe(1);
  });

  it("returns 1 when the longest side exactly equals the cap", () => {
    expect(rasterScale({ minX: 0, minY: 0, maxX: 2048, maxY: 100, width: 2048, height: 100 })).toBe(1);
  });

  it("returns a <1 factor when the width exceeds the cap", () => {
    const bounds = { minX: 0, minY: 0, maxX: 4096, maxY: 1000, width: 4096, height: 1000 };
    const scale = rasterScale(bounds);
    expect(scale).toBeLessThan(1);
    expect(bounds.width * scale).toBeCloseTo(2048);
  });

  it("scales both sides down proportionally so neither exceeds the cap", () => {
    const bounds = { minX: 0, minY: 0, maxX: 6000, maxY: 3000, width: 6000, height: 3000 };
    const scale = rasterScale(bounds);
    expect(bounds.width * scale).toBeLessThanOrEqual(2048 + 1e-9);
    expect(bounds.height * scale).toBeLessThanOrEqual(2048 + 1e-9);
  });

  it("respects a custom maxSide", () => {
    const bounds = { minX: 0, minY: 0, maxX: 1000, maxY: 1000, width: 1000, height: 1000 };
    expect(rasterScale(bounds, 500)).toBeCloseTo(0.5);
  });
});

describe("screenToWorld / worldToScreen (view transform round-trip)", () => {
  it("inverts the pan/zoom transform", () => {
    const view = { x: 100, y: 50, zoom: 2 };
    const rect = { left: 0, top: 0 };
    expect(screenToWorld(300, 150, rect, view)).toEqual({ x: 100, y: 50 });
  });

  it("accounts for the container offset", () => {
    const view = { x: 0, y: 0, zoom: 1 };
    const rect = { left: 40, top: 20 };
    expect(screenToWorld(60, 30, rect, view)).toEqual({ x: 20, y: 10 });
  });

  it("worldToScreen is the forward inverse of screenToWorld", () => {
    const view = { x: 25, y: -10, zoom: 1.5 };
    const world = { x: 12, y: 8 };
    const screen = worldToScreen(world, view);
    // container at origin, so screen coords == client coords here
    expect(screenToWorld(screen.x, screen.y, { left: 0, top: 0 }, view)).toEqual(world);
  });
});
