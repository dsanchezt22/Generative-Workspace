import { describe, expect, it } from "vitest";
import { AUTONOMOUS_ACTION_TYPES, deriveTier, overviewMeta, tierLabel } from "./structure";
import type { PageOverview } from "./types";

describe("deriveTier — client mirror of the fail-closed tier", () => {
  it("marks every structure-allowed action type autonomous", () => {
    for (const t of ["watch", "summarize", "track", "remind", "draft"]) {
      expect(deriveTier(t)).toBe("autonomous");
    }
  });

  it("the mirrored set is exactly the five structure action types", () => {
    expect([...AUTONOMOUS_ACTION_TYPES].sort()).toEqual(
      ["draft", "remind", "summarize", "track", "watch"],
    );
  });

  it("anything else needs your tap (fail-closed — never grants autonomy)", () => {
    for (const t of ["send_email", "pay", "delete_data", "archive_module", "", "garbage"]) {
      expect(deriveTier(t)).toBe("needs-your-tap");
    }
  });

  it("labels are the frozen uppercase chips", () => {
    expect(tierLabel("autonomous")).toBe("AUTONOMOUS");
    expect(tierLabel("needs-your-tap")).toBe("NEEDS YOUR TAP");
  });
});

describe("overviewMeta — the tile / AppFrame status line", () => {
  const now = Date.parse("2026-07-06T12:00:00Z");
  const ov = (o: Partial<PageOverview>): PageOverview => ({
    modules: 0,
    automations: 0,
    last_run_at: null,
    ...o,
  });

  it("shows just the module count when nothing has run and there are no agents", () => {
    expect(overviewMeta(ov({ modules: 3 }), now)).toBe("3 modules");
  });

  it("singularizes one module", () => {
    expect(overviewMeta(ov({ modules: 1 }), now)).toBe("1 module");
  });

  it("appends the run line only when last_run_at is present", () => {
    const iso = new Date(now - 5 * 60_000).toISOString();
    expect(overviewMeta(ov({ modules: 2, last_run_at: iso }), now)).toBe(
      "2 modules · agent ran 5m ago",
    );
  });

  it("appends the agent count only when the page has automations", () => {
    expect(overviewMeta(ov({ modules: 4, automations: 2 }), now)).toBe("4 modules · 2 agents");
  });

  it("composes all three parts in order", () => {
    const iso = new Date(now - 3 * 3_600_000).toISOString();
    expect(overviewMeta(ov({ modules: 5, automations: 1, last_run_at: iso }), now)).toBe(
      "5 modules · agent ran 3h ago · 1 agent",
    );
  });

  it("never fabricates data for a missing overview", () => {
    expect(overviewMeta(undefined, now)).toBe("0 modules");
  });
});
