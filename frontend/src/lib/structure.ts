// Pure helpers for the V2 SURF surfaces — the structure proposal card's tier
// chip and the app-tile / AppFrame overview meta line. Kept DOM-free so the
// load-bearing bits (tier derivation, the meta formatter) are unit-tested in
// isolation (the house convention; the components stay untested).

import type { PageOverview } from "./types";
import { relativeTime } from "./pulse";

// Reconciled ruling 4: a structure automation carries `action_type`, NOT a tier.
// The card derives the chip client-side from a mirrored const — the SAME five
// action types the server allows in a structure are all autonomous today; any
// other type would need your tap. (The server derives the real floor from
// ACTION_SPECS; this mirror is display-only and can never grant autonomy the
// backend didn't.)
export const AUTONOMOUS_ACTION_TYPES = new Set([
  "watch",
  "summarize",
  "track",
  "remind",
  "draft",
]);

export type Tier = "autonomous" | "needs-your-tap";

export function deriveTier(actionType: string): Tier {
  return AUTONOMOUS_ACTION_TYPES.has(actionType) ? "autonomous" : "needs-your-tap";
}

export function tierLabel(tier: Tier): string {
  return tier === "autonomous" ? "AUTONOMOUS" : "NEEDS YOUR TAP";
}

// The Geist Mono status line shown on a portal tile and in the AppFrame:
//   "{n} modules"  (+ " · agent ran {relative}" only when last_run_at is set)
//   (+ " · {k} agents" only when the page has automations)
// Never fabricates the run line — a page whose automations haven't run omits it.
export function overviewMeta(overview: PageOverview | undefined, now: number): string {
  const modules = overview?.modules ?? 0;
  const parts = [`${modules} module${modules === 1 ? "" : "s"}`];
  if (overview?.last_run_at) {
    const rel = relativeTime(overview.last_run_at, now);
    if (rel) parts.push(`agent ran ${rel}`);
  }
  const agents = overview?.automations ?? 0;
  if (agents > 0) parts.push(`${agents} agent${agents === 1 ? "" : "s"}`);
  return parts.join(" · ");
}
