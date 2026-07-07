"use client";

import { useRef } from "react";
import { runAssembly } from "./assembly";
import { prefersReducedMotion } from "./motion";
import { useIsoLayoutEffect } from "./useIsoLayoutEffect";

// Runs the signature "module build" assembly on a Pulse row when it mounts —
// so cards/rows CONSTRUCT into place rather than fade (DESIGN-ETHOS §1.1/§10).
// Shares the reduced-motion gate (prefersReducedMotion) with the module build
// and the canvas zoom; under reduced motion the finished row is already correct,
// so we no-op. Fires via the isomorphic layout effect so the seed state is set
// before paint (no first-frame flash). runAssembly picks the beats it finds via
// [data-assembly] and skips the rest, so a row only needs whichever scaffold
// elements it renders.
export function useAssembly<T extends HTMLElement>(index = 0) {
  const ref = useRef<T | null>(null);
  useIsoLayoutEffect(() => {
    if (!ref.current) return;
    if (prefersReducedMotion()) return; // final state renders instantly — no animation
    return runAssembly(ref.current, index);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return ref;
}
