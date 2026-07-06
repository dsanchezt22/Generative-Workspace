import { describe, expect, it } from "vitest";
import {
  clampZoom,
  pinchZoomFactor,
  pointerDistance,
  pointerMidpoint,
  zoomTowardPoint,
} from "./pinchZoom";

describe("clampZoom", () => {
  it("passes a value already within range through unchanged", () => {
    expect(clampZoom(1, 0.3, 2)).toBe(1);
  });

  it("clamps below the minimum", () => {
    expect(clampZoom(0.1, 0.3, 2)).toBe(0.3);
  });

  it("clamps above the maximum", () => {
    expect(clampZoom(5, 0.3, 2)).toBe(2);
  });
});

describe("zoomTowardPoint (the wheel/button/pinch anchor transform)", () => {
  it("keeps the world point under screenPoint fixed on screen", () => {
    const view = { x: 0, y: 0, zoom: 1 };
    const screenPoint = { x: 100, y: 50 };
    const next = zoomTowardPoint(view, 2, screenPoint, 0.3, 4);
    // world point under (100,50) at zoom=1,x=0,y=0 is (100,50) — after
    // doubling zoom, that same world point must still map to (100,50).
    const worldX = (screenPoint.x - next.x) / next.zoom;
    const worldY = (screenPoint.y - next.y) / next.zoom;
    expect(worldX).toBeCloseTo(100);
    expect(worldY).toBeCloseTo(50);
    expect(next.zoom).toBe(2);
  });

  it("clamps the resulting zoom to the given range", () => {
    const view = { x: 10, y: 10, zoom: 1.9 };
    const next = zoomTowardPoint(view, 2, { x: 0, y: 0 }, 0.3, 2);
    expect(next.zoom).toBe(2);
  });

  it("clamps at the minimum too", () => {
    const view = { x: 10, y: 10, zoom: 0.4 };
    const next = zoomTowardPoint(view, 0.1, { x: 0, y: 0 }, 0.3, 2);
    expect(next.zoom).toBe(0.3);
  });

  it("is a no-op on x/y when factor is 1 (zoom unchanged)", () => {
    const view = { x: 42, y: -7, zoom: 1.5 };
    const next = zoomTowardPoint(view, 1, { x: 200, y: 200 }, 0.3, 2);
    expect(next).toEqual(view);
  });
});

describe("pointerDistance / pointerMidpoint (pinch geometry)", () => {
  it("computes the straight-line distance between two pointers", () => {
    expect(pointerDistance({ x: 0, y: 0 }, { x: 3, y: 4 })).toBe(5);
  });

  it("returns 0 for two coincident pointers", () => {
    expect(pointerDistance({ x: 10, y: 10 }, { x: 10, y: 10 })).toBe(0);
  });

  it("computes the midpoint between two pointers", () => {
    expect(pointerMidpoint({ x: 0, y: 0 }, { x: 10, y: 20 })).toEqual({ x: 5, y: 10 });
  });
});

describe("pinchZoomFactor", () => {
  it("returns >1 when fingers spread apart (zoom in)", () => {
    expect(pinchZoomFactor(100, 150)).toBeCloseTo(1.5);
  });

  it("returns <1 when fingers pinch together (zoom out)", () => {
    expect(pinchZoomFactor(100, 50)).toBeCloseTo(0.5);
  });

  it("returns 1 when distance is unchanged", () => {
    expect(pinchZoomFactor(120, 120)).toBe(1);
  });

  it("guards a degenerate (zero) previous distance instead of dividing by zero", () => {
    expect(pinchZoomFactor(0, 80)).toBe(1);
  });

  it("guards a negative previous distance the same way", () => {
    expect(pinchZoomFactor(-1, 80)).toBe(1);
  });
});
