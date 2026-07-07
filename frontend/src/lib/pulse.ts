// Pulse — the pure, testable logic behind the "what happened / what needs your
// tap" surface. Kept out of the components (which stay untested, house
// convention) so the load-bearing bits — the journal register map, relative
// time, and the optimistic approve/reject flow — are unit-tested in isolation
// (vitest, node env). No DOM, no React here.

import type { ActivityEntry, ActivityKind, ApprovalOut } from "./types";

// ── Journal register ───────────────────────────────────────────────────────
// Every ActivityKind → a Geist Mono uppercase label + a muted status token
// (never neon — DESIGN-ETHOS §2.5/§10). `held` and `skipped` share the amber
// hold token but read differently ("NEEDS TAP" vs "HELD"). The " · SIMULATED"
// suffix on approved rows is applied by ActivityRow, not here (it's per-entry).
export interface KindRegister {
  label: string;
  colorToken: string; // a CSS var() reference — resolved by the row's style
}

const KIND_REGISTER: Record<ActivityKind, KindRegister> = {
  ran: { label: "RAN", colorToken: "var(--status-ok)" }, // muted sage
  held: { label: "NEEDS TAP", colorToken: "var(--status-hold)" }, // muted amber
  approved: { label: "DONE", colorToken: "var(--foreground)" }, // off-white
  rejected: { label: "DISMISSED", colorToken: "var(--muted)" }, // gray
  expired: { label: "EXPIRED", colorToken: "var(--gray-mid)" }, // dim gray
  failed: { label: "FAILED", colorToken: "var(--status-err)" }, // muted terracotta
  skipped: { label: "HELD", colorToken: "var(--status-hold)" }, // muted amber
};

// The runtime list of every kind — lets a test assert map completeness without
// a compile-time-only type, and drives any exhaustive UI iteration.
export const ACTIVITY_KINDS: ActivityKind[] = [
  "ran",
  "held",
  "approved",
  "rejected",
  "expired",
  "failed",
  "skipped",
];

export function kindRegister(kind: ActivityKind): KindRegister {
  return KIND_REGISTER[kind];
}

// ── Relative time ──────────────────────────────────────────────────────────
// "just now" / "5m ago" / "3h ago" / "2d ago" / "4w ago". `now` is injected
// (ms epoch) so it's deterministic under test — never reads the clock itself.
// An unparseable iso returns "" (no fabricated time — honest empty).
const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;
const WEEK = 7 * DAY;

export function relativeTime(iso: string, now: number): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const diff = now - t;
  if (diff < 45_000) return "just now";
  if (diff < HOUR) return `${Math.max(1, Math.round(diff / MIN))}m ago`;
  if (diff < DAY) return `${Math.floor(diff / HOUR)}h ago`;
  if (diff < WEEK) return `${Math.floor(diff / DAY)}d ago`;
  return `${Math.floor(diff / WEEK)}w ago`;
}

// ── Optimistic approve/reject flow ─────────────────────────────────────────
// The panel's single store for the two live lists. All mutations flow through
// this reducer so the optimistic tap flow is one tested seam:
//   submit  → mark the card in-flight (buttons show EXECUTING…, card disabled)
//   success → remove the card + prepend the returned journal row to the feed
//   conflict(409) → remove the card + flag a refetch (the truth diverged)
//   error(5xx)    → restore the card + carry the failure register onto it
// The feed lives here too so `success` can prepend without a refetch.

export const ACTIVITY_PAGE = 50; // mirrors the api.listActivity limit

export interface ApprovalItem {
  approval: ApprovalOut;
  pending: "approve" | "reject" | null; // in-flight mode; null = idle
  error: string | null; // last failure register (5xx), shown on the card
}

export interface PulseState {
  approvals: ApprovalItem[];
  activity: ActivityEntry[]; // newest first
  activityDone: boolean; // the last page came back short — nothing more to load
  needsRefetch: boolean; // a 409 means server truth diverged — re-sync both lists
}

export type PulseAction =
  | { type: "approvals/loaded"; approvals: ApprovalOut[] }
  | { type: "activity/loaded"; entries: ActivityEntry[]; append: boolean }
  | { type: "activity/prepend"; entry: ActivityEntry } // a run-now that executed
  | { type: "decision/submit"; id: string; mode: "approve" | "reject" }
  | { type: "decision/success"; id: string; activity: ActivityEntry }
  | { type: "decision/conflict"; id: string }
  | { type: "decision/error"; id: string; error: string }
  | { type: "refetch/clear" };

export function initialPulseState(): PulseState {
  return { approvals: [], activity: [], activityDone: false, needsRefetch: false };
}

function dedupeById(entries: ActivityEntry[]): ActivityEntry[] {
  const seen = new Set<string>();
  return entries.filter((e) => (seen.has(e.id) ? false : (seen.add(e.id), true)));
}

export function approvalReducer(state: PulseState, action: PulseAction): PulseState {
  switch (action.type) {
    case "approvals/loaded":
      // A fresh server read is the source of truth — drop stale in-flight/error.
      return {
        ...state,
        approvals: action.approvals.map((a) => ({ approval: a, pending: null, error: null })),
        needsRefetch: false,
      };

    case "activity/loaded": {
      const merged = action.append ? [...state.activity, ...action.entries] : action.entries;
      return {
        ...state,
        activity: dedupeById(merged),
        activityDone: action.entries.length < ACTIVITY_PAGE,
      };
    }

    case "activity/prepend": {
      const activity = state.activity.some((e) => e.id === action.entry.id)
        ? state.activity
        : [action.entry, ...state.activity];
      return { ...state, activity };
    }

    case "decision/submit":
      return {
        ...state,
        approvals: state.approvals.map((it) =>
          it.approval.id === action.id ? { ...it, pending: action.mode, error: null } : it,
        ),
      };

    case "decision/success": {
      const approvals = state.approvals.filter((it) => it.approval.id !== action.id);
      const activity = state.activity.some((e) => e.id === action.activity.id)
        ? state.activity
        : [action.activity, ...state.activity];
      return { ...state, approvals, activity };
    }

    case "decision/conflict":
      return {
        ...state,
        approvals: state.approvals.filter((it) => it.approval.id !== action.id),
        needsRefetch: true,
      };

    case "decision/error":
      return {
        ...state,
        approvals: state.approvals.map((it) =>
          it.approval.id === action.id ? { ...it, pending: null, error: action.error } : it,
        ),
      };

    case "refetch/clear":
      return { ...state, needsRefetch: false };

    default:
      return state;
  }
}
