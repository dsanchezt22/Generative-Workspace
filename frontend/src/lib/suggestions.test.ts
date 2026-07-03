import { describe, expect, it } from "vitest";
import { filterSuggestions, suggestionLabel } from "./suggestions";

describe("filterSuggestions (R-104: usage prompts → build-idea chips)", () => {
  it("keeps genuine build prompts", () => {
    expect(filterSuggestions(["Create a habit tracker", "Weekly meal planner for two"])).toEqual([
      "Create a habit tracker",
      "Weekly meal planner for two",
    ]);
  });

  it("drops file-upload log lines (📎 prefix)", () => {
    expect(filterSuggestions(["📎 receipt.png: extracted 3 line items", "Create a budget tracker"])).toEqual([
      "Create a budget tracker",
    ]);
  });

  it("drops terse fragments under 3 words", () => {
    expect(filterSuggestions(["budget", "add columns", "Create a reading list"])).toEqual([
      "Create a reading list",
    ]);
  });

  it("drops refine-combined preview prompts (em-dash join)", () => {
    expect(
      filterSuggestions(["Create a workout log — add a rest-day checkbox", "Create a workout log"]),
    ).toEqual(["Create a workout log"]);
  });

  it("drops refine imperatives that tweak an existing tool", () => {
    expect(
      filterSuggestions(["make it a bar chart instead", "change the currency to euros", "Create a savings goal tracker"]),
    ).toEqual(["Create a savings goal tracker"]);
  });

  it("dedupes case-insensitively and trims whitespace", () => {
    expect(filterSuggestions(["  Create a habit tracker ", "create a habit tracker"])).toEqual([
      "Create a habit tracker",
    ]);
  });

  it("returns empty when everything is filtered (caller falls back to static chips)", () => {
    expect(filterSuggestions(["📎 file.csv: ok", "budget", "make it blue"])).toEqual([]);
  });
});

describe("suggestionLabel (short chip label from a build prompt)", () => {
  it("strips a leading create/make/build article", () => {
    expect(suggestionLabel("Create a habit tracker")).toBe("Habit tracker");
    expect(suggestionLabel("build me an expense log")).toBe("Expense log");
  });

  it("truncates long prompts with an ellipsis", () => {
    expect(suggestionLabel("Create a comprehensive multi-year financial planning dashboard")).toMatch(/…$/);
  });

  it("falls back to the whole prompt when stripping would empty it", () => {
    expect(suggestionLabel("Reading list")).toBe("Reading list");
  });
});
