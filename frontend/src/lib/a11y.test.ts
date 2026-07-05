import { describe, expect, it } from "vitest";
import { arrowNudgeDelta, NUDGE_STEP, NUDGE_STEP_LARGE } from "./a11y";

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
