import type { DataSource, LiveValuePayload } from "./types";

/**
 * Pure helpers for the live-data render path (R-701/R-703): relative-time
 * formatting, the query→URL-params builder, and the provider→display-name
 * map. Kept dependency-free (no React) so `useLiveValue.ts` and `api.ts` can
 * both import them and vitest can cover them directly.
 */

// Off-mode detection (R-701 hardening): the backend's `TRUS_LIVE_DATA=off`
// marker carries a structured `disabled: true` (`routes/live.py`) — THAT
// boolean is the signal, never the human-readable error string (the backend
// keeps "Live data is disabled" in the payload for back-compat, but it's free
// to be reworded without turning off-mode into error chrome). Off-mode means
// "no live chrome at all"; a genuine provider/network failure (no flag) keeps
// the stale/unavailable chrome and stays manually usable.
export function isLiveDataDisabled(payload: LiveValuePayload | null | undefined): boolean {
  return payload?.disabled === true;
}

// Friendly provenance names (3-2 deferred Minor (a)): the backend's disabled
// marker echoes the raw provider path (`source: "weather"`), so the frontend
// computes its own display name from the known provider rather than trusting
// whatever `source` the response carries.
const PROVIDER_DISPLAY_NAMES: Record<string, string> = {
  weather: "Open-Meteo",
  nutrition: "Open Food Facts",
};

export function providerDisplayName(provider: string): string {
  return PROVIDER_DISPLAY_NAMES[provider] ?? provider;
}

// The route clamps `refresh_secs` to [60, 86400]; mirror that here so the
// frontend never requests (or polls at) an out-of-range interval.
export function clampRefreshSecs(secs: number | null | undefined): number {
  const v = typeof secs === "number" && Number.isFinite(secs) ? secs : 600;
  return Math.min(86400, Math.max(60, Math.round(v)));
}

// query dict → URL params. Only the keys each provider's route param actually
// reads are forwarded (weather: `place` OR `lat`+`lon`; nutrition: `food`),
// plus `refresh_secs` — mirrors `GET /api/live/{provider}`'s query params.
export function buildLiveQueryParams(
  provider: DataSource["provider"],
  query: DataSource["query"],
  refreshSecs: number,
): URLSearchParams {
  const params = new URLSearchParams();
  if (provider === "nutrition") {
    if (query.food != null) params.set("food", String(query.food));
  } else {
    if (query.place != null) {
      params.set("place", String(query.place));
    } else if (query.lat != null && query.lon != null) {
      params.set("lat", String(query.lat));
      params.set("lon", String(query.lon));
    }
  }
  params.set("refresh_secs", String(clampRefreshSecs(refreshSecs)));
  return params;
}

// "as of 3 min ago" — the freshness fragment (caller prepends "as of ").
export function formatRelativeTime(iso: string | null | undefined, now: Date | number = new Date()): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const nowMs = typeof now === "number" ? now : now.getTime();
  const diffSecs = Math.round((nowMs - then) / 1000);
  if (diffSecs < 45) return "just now";
  const diffMin = Math.round(diffSecs / 60);
  if (diffMin < 60) return `${diffMin} min ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr} hr ago`;
  const diffDay = Math.round(diffHr / 24);
  return `${diffDay} day${diffDay === 1 ? "" : "s"} ago`;
}

// Shared number formatting for a live (or live-augmented) value: an integer
// renders rounded/grouped, anything else to one decimal — mirrors the
// pre-existing MetricField behavior so the live path reads identically to
// the manual/computed one. `animated` lets callers pass a tweened (useCountUp)
// number while `raw` still decides integer-vs-decimal formatting.
export function formatLiveNumber(raw: number, animated: number = raw): string {
  if (!Number.isFinite(raw)) return "—";
  return raw % 1 === 0 ? Math.round(animated).toLocaleString() : animated.toFixed(1);
}
