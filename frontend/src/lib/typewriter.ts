// R-101: the rotating-headline typewriter, extracted as a pure step function so
// its type→hold→delete→advance cycle is unit-testable without a DOM. Both the
// old IntroSplash flourish and the new EntryScreen headline drive their
// setTimeout loop through nextTypewriterState — the effect just applies the
// returned state after `delayMs`. Starts from an empty string (SSR-safe: server
// and first client paint match; the ethos "typewriter starts empty" rule).

export interface TypewriterState {
  text: string;
  phraseIndex: number;
  deleting: boolean;
}

export interface TypewriterStep {
  state: TypewriterState;
  delayMs: number;
}

export interface TypewriterTiming {
  type: number; // per-character while typing
  hold: number; // pause once a phrase is fully typed
  delete: number; // per-character while deleting
  advance: number; // breath after a phrase is fully deleted, before the next
}

export const DEFAULT_TIMING: TypewriterTiming = { type: 55, hold: 1400, delete: 26, advance: 240 };

/**
 * Given the current typewriter state and the phrase set, returns the next state
 * plus how long to wait before applying it. The cycle: type the phrase one char
 * at a time → hold when complete → delete one char at a time → advance to the
 * next phrase (wrapping) once empty.
 */
export function nextTypewriterState(
  state: TypewriterState,
  phrases: string[],
  timing: TypewriterTiming = DEFAULT_TIMING,
): TypewriterStep {
  const { text, phraseIndex, deleting } = state;
  const full = phrases.length ? phrases[phraseIndex % phrases.length] : "";

  if (!deleting) {
    if (text.length < full.length) {
      return { state: { text: full.slice(0, text.length + 1), phraseIndex, deleting: false }, delayMs: timing.type };
    }
    // Fully typed — hold, then start deleting.
    return { state: { text, phraseIndex, deleting: true }, delayMs: timing.hold };
  }

  if (text.length > 0) {
    return { state: { text: full.slice(0, text.length - 1), phraseIndex, deleting: true }, delayMs: timing.delete };
  }
  // Fully deleted — advance to the next phrase (wrapping) and start typing again.
  return { state: { text: "", phraseIndex: phraseIndex + 1, deleting: false }, delayMs: timing.advance };
}
