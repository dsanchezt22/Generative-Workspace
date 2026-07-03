import { describe, expect, it } from "vitest";
import { appendTranscript, formatElapsed, pickAudioMime } from "./voiceRamble";

describe("pickAudioMime (R-201: MediaRecorder mime selection)", () => {
  it("prefers webm/opus when supported", () => {
    const isSupported = (t: string) => t === "audio/webm;codecs=opus" || t === "audio/webm";
    expect(pickAudioMime(isSupported)).toBe("audio/webm;codecs=opus");
  });

  it("falls back to plain webm when opus isn't supported", () => {
    const isSupported = (t: string) => t === "audio/webm";
    expect(pickAudioMime(isSupported)).toBe("audio/webm");
  });

  it("returns undefined when neither is supported (e.g. Safari) — caller uses the browser default", () => {
    expect(pickAudioMime(() => false)).toBeUndefined();
  });

  it("treats a throwing isSupported as unsupported rather than crashing", () => {
    const isSupported = () => {
      throw new Error("boom");
    };
    expect(pickAudioMime(isSupported)).toBeUndefined();
  });
});

describe("appendTranscript (R-201: append, never overwrite)", () => {
  it("returns the transcript alone when the input was empty", () => {
    expect(appendTranscript("", "track my workouts")).toBe("track my workouts");
  });

  it("returns the existing text alone when the transcript is empty/whitespace", () => {
    expect(appendTranscript("existing text", "   ")).toBe("existing text");
  });

  it("space-joins existing text and the transcript", () => {
    expect(appendTranscript("track my workouts", "and a budget too")).toBe(
      "track my workouts and a budget too",
    );
  });

  it("trims stray edge whitespace from both sides without collapsing interior spacing", () => {
    expect(appendTranscript("  hello   world  ", "  there  ")).toBe("hello   world there");
  });

  it("returns empty string when both are empty", () => {
    expect(appendTranscript("", "")).toBe("");
  });
});

describe("formatElapsed (mm:ss recording indicator)", () => {
  it("formats zero", () => {
    expect(formatElapsed(0)).toBe("0:00");
  });

  it("pads seconds under a minute", () => {
    expect(formatElapsed(7)).toBe("0:07");
  });

  it("rolls minutes over at 60s", () => {
    expect(formatElapsed(65)).toBe("1:05");
  });

  it("handles multi-minute rambles", () => {
    expect(formatElapsed(600)).toBe("10:00");
  });

  it("floors fractional seconds and clamps negatives to zero", () => {
    expect(formatElapsed(5.9)).toBe("0:05");
    expect(formatElapsed(-3)).toBe("0:00");
  });
});
