// R-502/R-504: pure geometry for the page-portal layer on the canvas. A child
// page renders as a world-coord tile on its parent's canvas (transformed by the
// SAME pan/zoom as modules and the sketch overlay). Extracted here so the
// non-trivial placement math is unit-testable without a DOM harness — Canvas.tsx
// keeps the pointer/drag plumbing (manual-traced), same split as sketchExport.ts.

// Tile footprint in WORLD units. Kept in sync with the tile's Tailwind sizing in
// Canvas.tsx (a matte "place you can enter", distinct from a module card).
export const PORTAL_W = 210;
export const PORTAL_H = 120;

// Auto-placement for a child whose portal position hasn't been set yet: a tidy
// row-wrapping SHELF in a negative-Y band ABOVE the module grid. The module
// auto-grid starts at (32, 96) (page.tsx) — sharing that origin put portal[0] at
// the EXACT world point of module[0], and since modules paint on top and capture
// the pointer, that first tile was invisible/un-clickable until the user panned.
// Modules only ever occupy y >= 96, so a band at y <= -48 can never collide with
// them, regardless of module count. Canvas.contentBounds includes the portal
// shelf, so fit-to-content keeps it framed (otherwise a negative-Y tile sits above
// the default viewport). Persistence (portal_x/portal_y) overrides this the moment
// the user drags the tile — this is only the first guess.
const PER_ROW = 4;
const GAP = 24;
const X0 = 32;
// First (bottom) shelf row: one tile-height + a clear gap above the modules.
const Y0 = -(PORTAL_H + 48); // = -168

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
    y: Y0 - row * (PORTAL_H + GAP), // rows stack UPWARD, staying clear of modules
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
