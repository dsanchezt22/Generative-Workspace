import { describe, expect, it } from "vitest";
import { autoPlacePortal, portalPosition, PORTAL_W, PORTAL_H } from "./portalLayout";

describe("autoPlacePortal (R-502: shelf ABOVE the module grid, no collision)", () => {
  it("places the first portal on a negative-Y shelf, clear of the module lane", () => {
    // The module auto-grid starts at (32, 96); the portal shelf must NOT share
    // that origin (portal[0] would be occluded under module[0]).
    expect(autoPlacePortal(0)).toEqual({ x: 32, y: -168 });
  });

  it("never lands in the module band (y >= 96)", () => {
    for (let i = 0; i < 12; i++) expect(autoPlacePortal(i).y).toBeLessThan(96);
  });

  it("advances along a row before wrapping", () => {
    const first = autoPlacePortal(0);
    const second = autoPlacePortal(1);
    expect(second.y).toBe(first.y); // same row
    expect(second.x).toBe(first.x + PORTAL_W + 24); // one tile + gap to the right
  });

  it("wraps UPWARD to a new row after PER_ROW (4) tiles", () => {
    const fourth = autoPlacePortal(4); // 5th tile → row 1, col 0
    expect(fourth.x).toBe(autoPlacePortal(0).x); // back to the first column
    expect(fourth.y).toBe(autoPlacePortal(0).y - (PORTAL_H + 24)); // one row up (away from modules)
  });

  it("is deterministic (same index → same point)", () => {
    expect(autoPlacePortal(3)).toEqual(autoPlacePortal(3));
  });
});

describe("portalPosition (R-504: stored placement overrides auto)", () => {
  it("uses the stored placement when both axes are set", () => {
    expect(portalPosition({ portal_x: 400, portal_y: -120 }, 0)).toEqual({ x: 400, y: -120 });
  });

  it("honors a stored placement at the world origin (0,0)", () => {
    // Regression guard: 0 is a valid coordinate — must not fall back to auto.
    expect(portalPosition({ portal_x: 0, portal_y: 0 }, 2)).toEqual({ x: 0, y: 0 });
  });

  it("falls back to auto-placement when unset", () => {
    expect(portalPosition({}, 1)).toEqual(autoPlacePortal(1));
    expect(portalPosition({ portal_x: null, portal_y: null }, 1)).toEqual(autoPlacePortal(1));
  });

  it("treats a half-set pair (one axis only) as unset", () => {
    expect(portalPosition({ portal_x: 400, portal_y: null }, 0)).toEqual(autoPlacePortal(0));
    expect(portalPosition({ portal_x: null, portal_y: -120 }, 0)).toEqual(autoPlacePortal(0));
  });
});
