import { describe, expect, it } from "vitest";
import {
  buildLiveQueryParams,
  clampRefreshSecs,
  formatLiveNumber,
  formatRelativeTime,
  isLiveDataDisabled,
  LIVE_DATA_DISABLED_ERROR,
  providerDisplayName,
} from "./liveFormat";

describe("providerDisplayName (R-701, 3-2 Minor (a) fold-in)", () => {
  it("maps weather to Open-Meteo", () => {
    expect(providerDisplayName("weather")).toBe("Open-Meteo");
  });
  it("maps nutrition to Open Food Facts", () => {
    expect(providerDisplayName("nutrition")).toBe("Open Food Facts");
  });
  it("falls back to the raw provider for anything unmapped", () => {
    expect(providerDisplayName("stocks")).toBe("stocks");
  });
});

describe("isLiveDataDisabled / LIVE_DATA_DISABLED_ERROR", () => {
  it("recognizes the exact disabled-marker text", () => {
    expect(isLiveDataDisabled(LIVE_DATA_DISABLED_ERROR)).toBe(true);
    expect(isLiveDataDisabled("Live data is disabled")).toBe(true);
  });
  it("treats any other error (or null) as a real failure, not disabled", () => {
    expect(isLiveDataDisabled("Could not reach Open-Meteo: timeout")).toBe(false);
    expect(isLiveDataDisabled(null)).toBe(false);
    expect(isLiveDataDisabled(undefined)).toBe(false);
  });
});

describe("clampRefreshSecs", () => {
  it("defaults to 600 when missing", () => {
    expect(clampRefreshSecs(undefined)).toBe(600);
    expect(clampRefreshSecs(null)).toBe(600);
  });
  it("clamps below the route's 60s floor", () => {
    expect(clampRefreshSecs(10)).toBe(60);
  });
  it("clamps above the route's 86400s ceiling", () => {
    expect(clampRefreshSecs(999999)).toBe(86400);
  });
  it("passes an in-range value through (rounded)", () => {
    expect(clampRefreshSecs(1200.4)).toBe(1200);
  });
});

describe("buildLiveQueryParams", () => {
  it("weather: a place name becomes ?place=", () => {
    const params = buildLiveQueryParams("weather", { place: "Palo Alto" }, 600);
    expect(params.get("place")).toBe("Palo Alto");
    expect(params.get("lat")).toBeNull();
    expect(params.get("refresh_secs")).toBe("600");
  });

  it("weather: lat+lon are forwarded when there's no place", () => {
    const params = buildLiveQueryParams("weather", { lat: 37.44, lon: -122.14 }, 900);
    expect(params.get("lat")).toBe("37.44");
    expect(params.get("lon")).toBe("-122.14");
    expect(params.get("place")).toBeNull();
  });

  it("weather: place takes precedence over lat/lon if both are present", () => {
    const params = buildLiveQueryParams("weather", { place: "Palo Alto", lat: 1, lon: 2 }, 600);
    expect(params.get("place")).toBe("Palo Alto");
    expect(params.get("lat")).toBeNull();
  });

  it("nutrition: a food name becomes ?food=", () => {
    const params = buildLiveQueryParams("nutrition", { food: "banana" }, 600);
    expect(params.get("food")).toBe("banana");
    expect(params.get("place")).toBeNull();
  });

  it("always includes a clamped refresh_secs", () => {
    const params = buildLiveQueryParams("nutrition", { food: "banana" }, 5);
    expect(params.get("refresh_secs")).toBe("60");
  });
});

describe("formatRelativeTime", () => {
  const now = new Date("2026-07-03T12:00:00Z");

  it("returns empty for a missing/invalid timestamp", () => {
    expect(formatRelativeTime(null, now)).toBe("");
    expect(formatRelativeTime(undefined, now)).toBe("");
    expect(formatRelativeTime("not-a-date", now)).toBe("");
  });

  it("reads 'just now' for anything under 45s", () => {
    expect(formatRelativeTime("2026-07-03T11:59:30Z", now)).toBe("just now");
  });

  it("reads minutes ago", () => {
    expect(formatRelativeTime("2026-07-03T11:57:00Z", now)).toBe("3 min ago");
  });

  it("reads hours ago", () => {
    expect(formatRelativeTime("2026-07-03T09:00:00Z", now)).toBe("3 hr ago");
  });

  it("reads days ago, pluralized", () => {
    expect(formatRelativeTime("2026-07-01T12:00:00Z", now)).toBe("2 days ago");
    expect(formatRelativeTime("2026-07-02T12:00:00Z", now)).toBe("1 day ago");
  });
});

describe("formatLiveNumber", () => {
  it("renders '—' for a non-finite raw value", () => {
    expect(formatLiveNumber(NaN)).toBe("—");
  });
  it("rounds+groups an integer raw value (using the animated tween if given)", () => {
    expect(formatLiveNumber(2000)).toBe("2,000");
    expect(formatLiveNumber(2000, 1999.6)).toBe("2,000");
  });
  it("shows one decimal for a non-integer raw value", () => {
    expect(formatLiveNumber(21.3)).toBe("21.3");
    expect(formatLiveNumber(21.3, 20.96)).toBe("21.0");
  });
});
