// R-1304: pure geometry for the canvas's zoom gestures — wheel-zoom, the +/-
// buttons, and two-finger pinch-zoom all zoom "toward a point": the world
// coordinate currently under that screen point stays fixed while the zoom
// changes. Extracted so this anchor math (and the pinch-specific distance/
// midpoint geometry) is unit-testable without a DOM/pointer-event harness —
// same split as sketchExport.ts.

export interface View {
  x: number;
  y: number;
  zoom: number;
}

export interface Point {
  x: number;
  y: number;
}

export function clampZoom(zoom: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, zoom));
}

/**
 * Zoom `view` by `factor` (clamped to [min,max]) while keeping the WORLD
 * point currently under `screenPoint` fixed on screen. The one anchor
 * transform shared by wheel-zoom, the +/- buttons (screenPoint = viewport
 * center), and pinch-zoom (screenPoint = the two fingers' midpoint).
 */
export function zoomTowardPoint(
  view: View,
  factor: number,
  screenPoint: Point,
  min: number,
  max: number,
): View {
  const zoom = clampZoom(view.zoom * factor, min, max);
  const wx = (screenPoint.x - view.x) / view.zoom;
  const wy = (screenPoint.y - view.y) / view.zoom;
  return { zoom, x: screenPoint.x - wx * zoom, y: screenPoint.y - wy * zoom };
}

// ---- Pinch-specific pure math -----------------------------------------

/** Euclidean distance between two active pointers (screen px). */
export function pointerDistance(a: Point, b: Point): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

/** Midpoint between two active pointers (screen px). */
export function pointerMidpoint(a: Point, b: Point): Point {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

/**
 * The per-step zoom factor for a pinch move: how much farther apart (>1) or
 * closer together (<1) the two fingers are now vs. the last sampled distance.
 * Sampled per pointermove (not from gesture start), matching onWheel's
 * per-tick pattern — avoids drift if a sample is missed mid-gesture. Guards a
 * degenerate (near-zero) previous distance so a finger-down glitch can never
 * produce Infinity/NaN and jump the zoom.
 */
export function pinchZoomFactor(prevDistance: number, nextDistance: number): number {
  if (prevDistance <= 0) return 1;
  return nextDistance / prevDistance;
}
