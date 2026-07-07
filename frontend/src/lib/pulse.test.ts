import { describe, expect, it } from "vitest";
import type { ActivityEntry, ApprovalOut } from "./types";
import {
  ACTIVITY_KINDS,
  ACTIVITY_PAGE,
  approvalReducer,
  initialPulseState,
  kindRegister,
  relativeTime,
  type PulseState,
} from "./pulse";

// ── fixtures ────────────────────────────────────────────────────────────────
const approval = (id: string): ApprovalOut => ({
  id,
  automation_id: `auto-${id}`,
  automation_name: "Nightly digest",
  action_type: "summarize",
  summary: "Will compile the digest",
  preview: null,
  status: "pending",
  expires_at: "2026-07-09T00:00:00Z",
  created_at: "2026-07-06T00:00:00Z",
  decided_at: null,
  executed_at: null,
});

const entry = (id: string, kind: ActivityEntry["kind"] = "approved"): ActivityEntry => ({
  id,
  kind,
  summary: `activity ${id}`,
  automation_id: null,
  automation_name: null,
  approval_id: null,
  simulated: false,
  created_at: "2026-07-06T00:00:00Z",
});

const withApprovals = (...ids: string[]): PulseState => ({
  ...initialPulseState(),
  approvals: ids.map((id) => ({ approval: approval(id), pending: null, error: null })),
});

// ── kindRegister ──────────────────────────────────────────────────────────
describe("kindRegister — the journal register map", () => {
  it("covers every ActivityKind with a non-empty label + colorToken", () => {
    for (const kind of ACTIVITY_KINDS) {
      const reg = kindRegister(kind);
      expect(reg.label.length).toBeGreaterThan(0);
      expect(reg.colorToken).toMatch(/^var\(--[\w-]+\)$/);
    }
  });

  it("uses the exact copy the design froze", () => {
    expect(kindRegister("ran").label).toBe("RAN");
    expect(kindRegister("held").label).toBe("NEEDS TAP");
    expect(kindRegister("approved").label).toBe("DONE");
    expect(kindRegister("rejected").label).toBe("DISMISSED");
    expect(kindRegister("expired").label).toBe("EXPIRED");
    expect(kindRegister("failed").label).toBe("FAILED");
    expect(kindRegister("skipped").label).toBe("HELD");
  });

  it("routes held and skipped to the amber hold token, failed to terracotta", () => {
    expect(kindRegister("held").colorToken).toBe("var(--status-hold)");
    expect(kindRegister("skipped").colorToken).toBe("var(--status-hold)");
    expect(kindRegister("failed").colorToken).toBe("var(--status-err)");
    expect(kindRegister("ran").colorToken).toBe("var(--status-ok)");
  });
});

// ── relativeTime ──────────────────────────────────────────────────────────
describe("relativeTime — injected clock, no fabrication", () => {
  const now = Date.parse("2026-07-06T12:00:00Z");
  const ago = (ms: number) => new Date(now - ms).toISOString();

  it("reads recent events as 'just now'", () => {
    expect(relativeTime(ago(10_000), now)).toBe("just now");
  });

  it("scales through minutes, hours, days, weeks", () => {
    expect(relativeTime(ago(5 * 60_000), now)).toBe("5m ago");
    expect(relativeTime(ago(3 * 3_600_000), now)).toBe("3h ago");
    expect(relativeTime(ago(2 * 86_400_000), now)).toBe("2d ago");
    expect(relativeTime(ago(3 * 7 * 86_400_000), now)).toBe("3w ago");
  });

  it("never shows '0m ago' — sub-minute past the just-now window rounds up to 1m", () => {
    expect(relativeTime(ago(50_000), now)).toBe("1m ago");
  });

  it("returns '' for an unparseable timestamp (no fabricated time)", () => {
    expect(relativeTime("not-a-date", now)).toBe("");
  });
});

// ── approvalReducer — the optimistic tap flow ───────────────────────────────
describe("approvalReducer — optimistic approve/reject", () => {
  it("submit marks only the tapped card in-flight and clears its prior error", () => {
    let state = withApprovals("a", "b");
    state = approvalReducer(state, { type: "decision/error", id: "a", error: "boom" });
    state = approvalReducer(state, { type: "decision/submit", id: "a", mode: "approve" });
    const a = state.approvals.find((it) => it.approval.id === "a")!;
    const b = state.approvals.find((it) => it.approval.id === "b")!;
    expect(a.pending).toBe("approve");
    expect(a.error).toBeNull();
    expect(b.pending).toBeNull();
  });

  it("success removes the card and prepends the returned journal row", () => {
    let state = withApprovals("a", "b");
    state = approvalReducer(state, { type: "decision/submit", id: "a", mode: "approve" });
    state = approvalReducer(state, { type: "decision/success", id: "a", activity: entry("act-1") });
    expect(state.approvals.map((it) => it.approval.id)).toEqual(["b"]);
    expect(state.activity[0].id).toBe("act-1");
  });

  it("success never double-prepends an activity already in the feed", () => {
    let state: PulseState = { ...withApprovals("a"), activity: [entry("act-1")] };
    state = approvalReducer(state, { type: "decision/success", id: "a", activity: entry("act-1") });
    expect(state.activity.filter((e) => e.id === "act-1")).toHaveLength(1);
  });

  it("conflict (409) removes the card and flags a refetch", () => {
    let state = withApprovals("a", "b");
    state = approvalReducer(state, { type: "decision/conflict", id: "a" });
    expect(state.approvals.map((it) => it.approval.id)).toEqual(["b"]);
    expect(state.needsRefetch).toBe(true);
  });

  it("error (5xx) restores the card to idle and carries the failure register", () => {
    let state = withApprovals("a");
    state = approvalReducer(state, { type: "decision/submit", id: "a", mode: "reject" });
    state = approvalReducer(state, { type: "decision/error", id: "a", error: "FAILED — timeout" });
    const a = state.approvals[0];
    expect(a.pending).toBeNull();
    expect(a.error).toBe("FAILED — timeout");
    expect(state.approvals).toHaveLength(1); // still present, honest in-place failure
  });

  it("refetch/clear lowers the flag once the panel has re-synced", () => {
    let state = approvalReducer(withApprovals("a"), { type: "decision/conflict", id: "a" });
    state = approvalReducer(state, { type: "refetch/clear" });
    expect(state.needsRefetch).toBe(false);
  });
});

// ── approvalReducer — the activity feed / pagination ────────────────────────
describe("approvalReducer — activity feed", () => {
  it("a fresh load replaces the feed and marks done when the page is short", () => {
    const state = approvalReducer(initialPulseState(), {
      type: "activity/loaded",
      entries: [entry("1"), entry("2")],
      append: false,
    });
    expect(state.activity.map((e) => e.id)).toEqual(["1", "2"]);
    expect(state.activityDone).toBe(true); // 2 < PAGE
  });

  it("a full page leaves room for more (not done)", () => {
    const full = Array.from({ length: ACTIVITY_PAGE }, (_, i) => entry(`e${i}`));
    const state = approvalReducer(initialPulseState(), {
      type: "activity/loaded",
      entries: full,
      append: false,
    });
    expect(state.activityDone).toBe(false);
  });

  it("append concatenates the next page and dedupes overlaps", () => {
    let state = approvalReducer(initialPulseState(), {
      type: "activity/loaded",
      entries: [entry("1"), entry("2")],
      append: false,
    });
    state = approvalReducer(state, {
      type: "activity/loaded",
      entries: [entry("2"), entry("3")], // "2" overlaps a keyset boundary
      append: true,
    });
    expect(state.activity.map((e) => e.id)).toEqual(["1", "2", "3"]);
  });
});
