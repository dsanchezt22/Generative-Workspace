// R-504 completion: pure resolution logic for the per-page viewport (pan/zoom).
// The server-saved view (pages.view_x/view_y/view_zoom, owner-scoped) is the
// cross-device truth; localStorage (`trus-view-${pageId}`) stays the instant
// offline fallback. Extracted here so the precedence + validation is unit-testable
// without a DOM harness — Canvas.tsx keeps the effect/debounce plumbing
// (manual-traced), same split as portalLayout.ts.

export interface ViewState {
  x: number;
  y: number;
  zoom: number;
}

export const DEFAULT_VIEW: ViewState = { x: 0, y: 0, zoom: 1 };

const isFiniteNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

// Canvas.tsx's ZOOM_MIN/ZOOM_MAX (the +/- buttons' clamp). The PATCH that saves
// a view is hand-craftable, so a persisted view_zoom can be anything — loading
// it back unclamped (e.g. 500) would open an unusable viewport.
const ZOOM_MIN = 0.3;
const ZOOM_MAX = 2;
const clampZoom = (z: number): number => Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z));

/**
 * The page's server-saved viewport, or null when it has none. All three fields
 * must be present and finite, and zoom positive — a partial or corrupt triple is
 * treated as unset (a zoom of 0/negative would render nothing / mirror the world).
 * A positive but out-of-range zoom is clamped to the canvas range.
 */
export function serverViewOf(
  page: { view_x?: number | null; view_y?: number | null; view_zoom?: number | null } | null | undefined,
): ViewState | null {
  if (!page) return null;
  if (isFiniteNum(page.view_x) && isFiniteNum(page.view_y) && isFiniteNum(page.view_zoom) && page.view_zoom > 0) {
    return { x: page.view_x, y: page.view_y, zoom: clampZoom(page.view_zoom) };
  }
  return null;
}

/** Parse the localStorage fallback; null on missing/corrupt/invalid payloads. */
export function parseStoredView(raw: string | null): ViewState | null {
  if (!raw) return null;
  try {
    const v = JSON.parse(raw) as Partial<ViewState> | null;
    if (v && isFiniteNum(v.x) && isFiniteNum(v.y) && isFiniteNum(v.zoom) && v.zoom > 0) {
      return { x: v.x, y: v.y, zoom: v.zoom };
    }
  } catch {
    /* corrupt JSON → fall through to null */
  }
  return null;
}

/**
 * Where a page's view opens: the server-saved view when there is one (the
 * cross-device resume), else the localStorage fallback, else the default.
 */
export function resolveInitialView(server: ViewState | null, localRaw: string | null): ViewState {
  return server ?? parseStoredView(localRaw) ?? DEFAULT_VIEW;
}

/** True when `next` differs from the last persisted view — the guard that stops
 * a freshly-loaded (or just-saved) view being echoed straight back as a PATCH. */
export function viewChanged(last: ViewState | null, next: ViewState): boolean {
  return !last || last.x !== next.x || last.y !== next.y || last.zoom !== next.zoom;
}
