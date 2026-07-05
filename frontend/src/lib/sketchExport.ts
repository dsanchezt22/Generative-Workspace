// R-221-223: pure geometry for the canvas sketch overlay — extracted so the
// non-trivial coordinate math (bbox for the snap raster, screen↔world mapping)
// is unit-testable without a DOM/canvas harness (Canvas.tsx itself keeps the
// raster + pointer plumbing, which is manual-traced; same split as voiceRamble.ts).

export interface Point {
  x: number;
  y: number;
}

// A stroke is a polyline of points in WORLD coordinates (canvas space, before
// the pan/zoom transform) — so strokes stick to the world, not the screen.
export type Stroke = Point[];

export interface Bounds {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
  width: number;
  height: number;
}

// The canvas view transform: world→screen is (world * zoom) + {x,y}.
export interface View {
  x: number;
  y: number;
  zoom: number;
}

/**
 * Axis-aligned bounding box of every point across all strokes, grown by `pad`
 * on each side. Returns null when there is nothing to bound (no strokes, or only
 * empty strokes) — the caller uses null to DISABLE the snap button (there's
 * nothing to rasterize). `pad` (the snap uses 24px) gives the rasterized sketch
 * a margin so edge strokes aren't clipped against the image border.
 */
export function strokeBounds(strokes: Stroke[], pad = 0): Bounds | null {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  let any = false;
  for (const stroke of strokes) {
    for (const p of stroke) {
      any = true;
      if (p.x < minX) minX = p.x;
      if (p.y < minY) minY = p.y;
      if (p.x > maxX) maxX = p.x;
      if (p.y > maxY) maxY = p.y;
    }
  }
  if (!any) return null;
  minX -= pad;
  minY -= pad;
  maxX += pad;
  maxY += pad;
  return { minX, minY, maxX, maxY, width: maxX - minX, height: maxY - minY };
}

// Stage-2b backlog (R-221): the offscreen snap raster is sized 1:1 to the
// stroke bbox — a sketch drawn across a huge world-space area (e.g. zoomed
// far out) could otherwise allocate an oversized canvas. `rasterScale`
// returns a uniform downscale factor (<=1) the rasterizer applies to both the
// canvas dimensions and the stroke coordinates it draws; 1 when the bbox
// already fits within `maxSide` on every side.
const MAX_RASTER_SIDE = 2048;

export function rasterScale(bounds: Bounds, maxSide = MAX_RASTER_SIDE): number {
  const longest = Math.max(bounds.width, bounds.height);
  if (longest <= maxSide) return 1;
  return maxSide / longest;
}

/**
 * Convert a pointer position (clientX/clientY) into WORLD coordinates — the
 * inverse of the Canvas view transform (`translate(view.x,view.y) scale(zoom)`
 * with origin at the container's top-left). Feeding world points to the overlay
 * means a stroke stays put when the user pans or zooms after drawing it.
 */
export function screenToWorld(
  clientX: number,
  clientY: number,
  rect: { left: number; top: number },
  view: View,
): Point {
  return {
    x: (clientX - rect.left - view.x) / view.zoom,
    y: (clientY - rect.top - view.y) / view.zoom,
  };
}

/**
 * Forward map: WORLD point → on-screen position relative to the container's
 * top-left. Used by the live overlay redraw so strokes render at a constant
 * pixel width regardless of zoom (draw in screen space, positions from world).
 */
export function worldToScreen(p: Point, view: View): Point {
  return { x: view.x + p.x * view.zoom, y: view.y + p.y * view.zoom };
}
