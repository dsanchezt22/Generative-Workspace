// R-502/R-504: pure geometry for the page-portal layer on the canvas. A child
// page renders as a world-coord tile on its parent's canvas (transformed by the
// SAME pan/zoom as modules and the sketch overlay). Extracted here so the
// non-trivial placement math is unit-testable without a DOM harness — Canvas.tsx
// keeps the pointer/drag plumbing (manual-traced), same split as sketchExport.ts.

// Tile footprint in WORLD units. Kept in sync with PortalTile's Tailwind sizing
// (a solid matte "app card", distinct from a module card — V2 SURF §5).
export const PORTAL_W = 240;
export const PORTAL_H = 140;

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

// V2 SURF §6: "zoom-in-is-launching". The forward launch tween animates the
// canvas view to this target — the tile centered at LAUNCH_ZOOM — then the page
// swaps under the scrim. The reverse (back) tween SEEDS the view at this exact
// value and animates out to the parent's saved view, so forward-target and
// reverse-seed are the same point for a given tile (the symmetry the tests pin).
// LAUNCH_ZOOM == the interactive ZOOM_MAX (2): never overshoot the clamp, so a
// mid-tween wheel/pinch gesture can't fight the tween.
export const LAUNCH_ZOOM = 2;

export function launchTargetView(
  pos: PortalPoint,
  rect: { width: number; height: number },
  zoom = LAUNCH_ZOOM,
): { x: number; y: number; zoom: number } {
  const cx = pos.x + PORTAL_W / 2;
  const cy = pos.y + PORTAL_H / 2;
  return { zoom, x: rect.width / 2 - cx * zoom, y: rect.height / 2 - cy * zoom };
}
