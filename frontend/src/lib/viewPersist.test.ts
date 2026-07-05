import { describe, expect, it } from "vitest";
import {
  DEFAULT_VIEW,
  parseStoredView,
  resolveInitialView,
  serverViewOf,
  viewChanged,
} from "./viewPersist";

describe("serverViewOf (R-504: the page row's saved viewport)", () => {
  it("returns the view when all three fields are set", () => {
    expect(serverViewOf({ view_x: -320.25, view_y: 48, view_zoom: 0.75 })).toEqual({
      x: -320.25,
      y: 48,
      zoom: 0.75,
    });
  });

  it("treats an unsaved page (nulls) as no server view", () => {
    expect(serverViewOf({ view_x: null, view_y: null, view_zoom: null })).toBeNull();
    expect(serverViewOf({})).toBeNull();
    expect(serverViewOf(null)).toBeNull();
    expect(serverViewOf(undefined)).toBeNull();
  });

  it("treats a partial triple as unset (a view is meaningless without all axes)", () => {
    expect(serverViewOf({ view_x: 10, view_y: 20, view_zoom: null })).toBeNull();
    expect(serverViewOf({ view_x: 10, view_y: null, view_zoom: 1 })).toBeNull();
  });

  it("rejects a non-positive or non-finite zoom", () => {
    expect(serverViewOf({ view_x: 0, view_y: 0, view_zoom: 0 })).toBeNull();
    expect(serverViewOf({ view_x: 0, view_y: 0, view_zoom: -1 })).toBeNull();
    expect(serverViewOf({ view_x: 0, view_y: 0, view_zoom: NaN })).toBeNull();
  });
});

describe("parseStoredView (localStorage offline fallback)", () => {
  it("parses a valid stored view", () => {
    expect(parseStoredView('{"x":5,"y":-7,"zoom":1.2}')).toEqual({ x: 5, y: -7, zoom: 1.2 });
  });

  it("returns null on missing/corrupt/invalid payloads", () => {
    expect(parseStoredView(null)).toBeNull();
    expect(parseStoredView("")).toBeNull();
    expect(parseStoredView("not json")).toBeNull();
    expect(parseStoredView('{"x":1}')).toBeNull();
    expect(parseStoredView('{"x":1,"y":2,"zoom":0}')).toBeNull();
    expect(parseStoredView('{"x":"1","y":2,"zoom":1}')).toBeNull();
  });
});

describe("resolveInitialView (server > localStorage > default)", () => {
  const server = { x: 1, y: 2, zoom: 0.5 };
  const localRaw = '{"x":9,"y":9,"zoom":2}';

  it("prefers the server view when present (cross-device resume)", () => {
    expect(resolveInitialView(server, localRaw)).toEqual(server);
  });

  it("falls back to localStorage when the server has none", () => {
    expect(resolveInitialView(null, localRaw)).toEqual({ x: 9, y: 9, zoom: 2 });
  });

  it("falls back to the default when both are absent/corrupt", () => {
    expect(resolveInitialView(null, null)).toEqual(DEFAULT_VIEW);
    expect(resolveInitialView(null, "garbage")).toEqual(DEFAULT_VIEW);
  });
});

describe("viewChanged (echo-PATCH guard)", () => {
  it("is false for an identical view (a just-loaded view is never re-saved)", () => {
    expect(viewChanged({ x: 1, y: 2, zoom: 1 }, { x: 1, y: 2, zoom: 1 })).toBe(false);
  });

  it("is true when any axis moved, or nothing was persisted yet", () => {
    expect(viewChanged({ x: 1, y: 2, zoom: 1 }, { x: 3, y: 2, zoom: 1 })).toBe(true);
    expect(viewChanged({ x: 1, y: 2, zoom: 1 }, { x: 1, y: 0, zoom: 1 })).toBe(true);
    expect(viewChanged({ x: 1, y: 2, zoom: 1 }, { x: 1, y: 2, zoom: 1.2 })).toBe(true);
    expect(viewChanged(null, { x: 0, y: 0, zoom: 1 })).toBe(true);
  });
});
