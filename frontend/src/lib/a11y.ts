// Pure keyboard-accessibility decisions (R-1306). DOM wiring lives in the
// components (Module.tsx arrow-nudge) and useDialog.ts (the dialog-floor
// hook) — the math is here so vitest can pin it.

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

/** What counts as a dialog's tabbable (mirrors ProfilePanel's proven trap). */
export const TABBABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Focus-trap cycle: given the focused element's index among a dialog's
 * tabbables, decide where Tab / Shift+Tab must move focus. `null` means the
 * move is interior — let the browser handle it natively (preserves natural
 * tab order; only the edges wrap). An index of -1 (focus escaped or sits on
 * a non-tabbable) pulls focus back into the dialog.
 */
export function trapTabTarget(
  activeIndex: number,
  count: number,
  shiftKey: boolean,
): number | null {
  if (count === 0) return null;
  if (activeIndex === -1) return shiftKey ? count - 1 : 0;
  if (shiftKey && activeIndex === 0) return count - 1;
  if (!shiftKey && activeIndex === count - 1) return 0;
  return null;
}
