// R-502/R-504: pure geometry for the page-portal layer on the canvas. A child
// page renders as a world-coord tile on its parent's canvas (transformed by the
// SAME pan/zoom as modules and the sketch overlay). Extracted here so the
// non-trivial placement math is unit-testable without a DOM harness — Canvas.tsx
// keeps the pointer/drag plumbing (manual-traced), same split as sketchExport.ts.

// Tile footprint in WORLD units. Kept in sync with the tile's Tailwind sizing in
// Canvas.tsx (a matte "place you can enter", distinct from a module card).
export const PORTAL_W = 210;
export const PORTAL_H = 120;

// Auto-placement grid for a child whose portal position hasn't been set yet: a
// tidy row-wrapping stack near the world origin, clearing the fixed 56px header
// band (Y0 mirrors the module grid's clearance) so a freshly-nested page is
// visible at the default view. Persistence (portal_x/portal_y) overrides this the
// moment the user drags the tile — this is only the first guess.
const PER_ROW = 4;
const GAP = 24;
const X0 = 32;
const Y0 = 96;

export interface PortalPoint {
  x: number;
  y: number;
}

/** World position for the `index`-th auto-placed portal (no stored coords). */
export function autoPlacePortal(index: number): PortalPoint {
  const col = index % PER_ROW;
  const row = Math.floor(index / PER_ROW);
  return {
    x: X0 + col * (PORTAL_W + GAP),
    y: Y0 + row * (PORTAL_H + GAP),
  };
}

/**
 * Resolve a child page's portal position: its stored (portal_x, portal_y) when
 * BOTH are present (a placement the user dragged, R-504), else the deterministic
 * auto-placement for its ordinal. A half-set pair (only one axis) is treated as
 * unset — placement is meaningless without both axes.
 */
export function portalPosition(
  page: { portal_x?: number | null; portal_y?: number | null },
  index: number,
): PortalPoint {
  if (typeof page.portal_x === "number" && typeof page.portal_y === "number") {
    return { x: page.portal_x, y: page.portal_y };
  }
  return autoPlacePortal(index);
}
