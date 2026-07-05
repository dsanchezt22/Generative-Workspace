"use client";

import { useEffect, useRef, type KeyboardEvent as ReactKeyboardEvent, type RefObject } from "react";
import { TABBABLE_SELECTOR, trapTabTarget } from "./a11y";

// R-1306: the one dialog-floor hook — focus moves INTO the overlay on open,
// RESTORES to the opener on close, Escape closes (consumed so page.tsx's
// global Escape doesn't also fire), and Tab cycles inside. Extracted from
// ProfilePanel's proven container-scoped pattern (Stage 3): the handlers live
// on the overlay's root via onKeyDown (bubble), NOT on window — so when a
// ConfirmDialog opens as a SIBLING (the 2a-3 containing-block lesson), focus
// sits inside that dialog and this trap simply never fires; the dialog's
// capture-phase Escape owns the keyboard (no duelling traps, per 3-8).
//
// Deliberately NOT adopted by ConfirmDialog/EntryScreen: ConfirmDialog must
// consume Escape on the window CAPTURE phase so it beats its host panel's
// handlers regardless of focus (that choice is load-bearing); EntryScreen
// routes Escape through its dissolve choreography and focuses the text field
// (not its first tabbable, the mic) on open.
//
// Usage: spread `ref` + `onKeyDown` onto the overlay's root element. For
// components that stay mounted while closed, pass their `open` flag; for
// conditionally-rendered overlays, pass `true` (mount IS open).
export function useDialog<T extends HTMLElement>(
  open: boolean,
  onClose: () => void,
  // Optional explicit first-focus target (e.g. a Close button when the first
  // tabbable in DOM order is a destructive action like "Clear").
  initialFocus?: RefObject<HTMLElement | null>,
) {
  const ref = useRef<T | null>(null);
  // Latest onClose without re-running the open effect on parent re-renders
  // (the ConfirmDialog lesson — recreated callbacks must not re-steal focus).
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);
  const initialFocusRef = useRef(initialFocus);
  useEffect(() => {
    initialFocusRef.current = initialFocus;
  }, [initialFocus]);

  // Focus into the overlay on open; hand focus back to the opener on close —
  // only if it's still in the document (it may have been archived/deleted).
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const nodes = ref.current?.querySelectorAll<HTMLElement>(TABBABLE_SELECTOR);
    const first = nodes && Array.from(nodes).find((el) => el.offsetParent !== null);
    (initialFocusRef.current?.current ?? first ?? ref.current)?.focus();
    return () => {
      if (prev?.isConnected) prev.focus();
    };
  }, [open]);

  const onKeyDown = (e: ReactKeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopPropagation(); // page.tsx's global Escape must not also fire
      onCloseRef.current();
      return;
    }
    if (e.key !== "Tab" || !ref.current) return;
    const nodes = ref.current.querySelectorAll<HTMLElement>(TABBABLE_SELECTOR);
    const list = Array.from(nodes).filter((el) => el.offsetParent !== null);
    const idx = list.indexOf(document.activeElement as HTMLElement);
    const target = trapTabTarget(idx, list.length, e.shiftKey);
    if (target !== null) {
      e.preventDefault();
      list[target]?.focus();
    }
  };

  return { ref, onKeyDown };
}
