import { describe, expect, it } from "vitest";
import { DEFAULT_TIMING, nextTypewriterState, type TypewriterState } from "./typewriter";

const PHRASES = ["ab", "cd"];

describe("nextTypewriterState (R-101: rotating-headline cycle)", () => {
  it("types one character at a time from empty", () => {
    const step = nextTypewriterState({ text: "", phraseIndex: 0, deleting: false }, PHRASES);
    expect(step.state).toEqual({ text: "a", phraseIndex: 0, deleting: false });
    expect(step.delayMs).toBe(DEFAULT_TIMING.type);
  });

  it("holds, then flips to deleting once the phrase is fully typed", () => {
    const step = nextTypewriterState({ text: "ab", phraseIndex: 0, deleting: false }, PHRASES);
    expect(step.state).toEqual({ text: "ab", phraseIndex: 0, deleting: true });
    expect(step.delayMs).toBe(DEFAULT_TIMING.hold);
  });

  it("deletes one character at a time", () => {
    const step = nextTypewriterState({ text: "ab", phraseIndex: 0, deleting: true }, PHRASES);
    expect(step.state).toEqual({ text: "a", phraseIndex: 0, deleting: true });
    expect(step.delayMs).toBe(DEFAULT_TIMING.delete);
  });

  it("advances to the next phrase once fully deleted", () => {
    const step = nextTypewriterState({ text: "", phraseIndex: 0, deleting: true }, PHRASES);
    expect(step.state).toEqual({ text: "", phraseIndex: 1, deleting: false });
    expect(step.delayMs).toBe(DEFAULT_TIMING.advance);
  });

  it("wraps the phrase index modulo the phrase set", () => {
    // From the last phrase, advancing lands on index 2, which resolves to
    // phrases[2 % 2] = phrases[0] on the next type step.
    const advanced = nextTypewriterState({ text: "", phraseIndex: 1, deleting: true }, PHRASES);
    expect(advanced.state.phraseIndex).toBe(2);
    const typed = nextTypewriterState(advanced.state, PHRASES);
    expect(typed.state.text).toBe("a"); // first char of phrases[0]
  });

  it("never crashes on an empty phrase set (returns a stable hold)", () => {
    const state: TypewriterState = { text: "", phraseIndex: 0, deleting: false };
    const step = nextTypewriterState(state, []);
    expect(step.state.text).toBe("");
  });
});
