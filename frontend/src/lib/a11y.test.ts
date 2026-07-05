import { describe, expect, it } from "vitest";
import { arrowNudgeDelta, NUDGE_STEP, NUDGE_STEP_LARGE, trapTabTarget } from "./a11y";

describe("arrowNudgeDelta (module keyboard nudge, R-1306)", () => {
  it("maps each arrow to a single-axis step of NUDGE_STEP", () => {
    expect(arrowNudgeDelta("ArrowLeft", false)).toEqual({ dx: -NUDGE_STEP, dy: 0 });
    expect(arrowNudgeDelta("ArrowRight", false)).toEqual({ dx: NUDGE_STEP, dy: 0 });
    expect(arrowNudgeDelta("ArrowUp", false)).toEqual({ dx: 0, dy: -NUDGE_STEP });
    expect(arrowNudgeDelta("ArrowDown", false)).toEqual({ dx: 0, dy: NUDGE_STEP });
  });

  it("Shift takes the larger hop", () => {
    expect(arrowNudgeDelta("ArrowRight", true)).toEqual({ dx: NUDGE_STEP_LARGE, dy: 0 });
    expect(arrowNudgeDelta("ArrowUp", true)).toEqual({ dx: 0, dy: -NUDGE_STEP_LARGE });
  });

  it("returns null for non-arrow keys so the event passes through", () => {
    expect(arrowNudgeDelta("Enter", false)).toBeNull();
    expect(arrowNudgeDelta("Tab", false)).toBeNull();
    expect(arrowNudgeDelta("a", true)).toBeNull();
    expect(arrowNudgeDelta("Escape", false)).toBeNull();
  });
});

describe("trapTabTarget (dialog focus-trap Tab cycle, R-1306)", () => {
  it("wraps forward from the last tabbable to the first", () => {
    expect(trapTabTarget(2, 3, false)).toBe(0);
  });

  it("wraps backward from the first tabbable to the last", () => {
    expect(trapTabTarget(0, 3, true)).toBe(2);
  });

  it("leaves interior moves to the browser (null)", () => {
    expect(trapTabTarget(1, 3, false)).toBeNull();
    expect(trapTabTarget(1, 3, true)).toBeNull();
  });

  it("pulls escaped focus (index -1) back into the dialog", () => {
    expect(trapTabTarget(-1, 3, false)).toBe(0);
    expect(trapTabTarget(-1, 3, true)).toBe(2);
  });

  it("cycles a single tabbable onto itself", () => {
    expect(trapTabTarget(0, 1, false)).toBe(0);
    expect(trapTabTarget(0, 1, true)).toBe(0);
  });

  it("no-ops when the dialog has no tabbables", () => {
    expect(trapTabTarget(0, 0, false)).toBeNull();
    expect(trapTabTarget(-1, 0, true)).toBeNull();
  });
});
