// Pure keyboard-accessibility decisions (R-1306). DOM wiring lives in the
// components (Module.tsx arrow-nudge) — the math is here so vitest can pin it.

/** World-units a focused module moves per arrow press; Shift takes the big hop. */
export const NUDGE_STEP = 16;
export const NUDGE_STEP_LARGE = 64;

/**
 * Arrow-key → position delta for nudging a focused canvas module.
 * Returns null for any non-arrow key (caller lets the event pass through).
 */
export function arrowNudgeDelta(
  key: string,
  shiftKey: boolean,
): { dx: number; dy: number } | null {
  const step = shiftKey ? NUDGE_STEP_LARGE : NUDGE_STEP;
  switch (key) {
    case "ArrowLeft":
      return { dx: -step, dy: 0 };
    case "ArrowRight":
      return { dx: step, dy: 0 };
    case "ArrowUp":
      return { dx: 0, dy: -step };
    case "ArrowDown":
      return { dx: 0, dy: step };
    default:
      return null;
  }
}
