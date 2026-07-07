"use client";

import { useEffect, useRef } from "react";
import { runAssembly } from "./assembly";

// Runs the signature "module build" assembly on a Pulse row when it mounts —
// so cards/rows CONSTRUCT into place rather than fade (DESIGN-ETHOS §1.1/§10).
// The reduced-motion gate is copied verbatim from Module.tsx:102-111: honour a
// forced "reduced", else the OS preference unless "full" is forced. Under
// reduced motion the finished row is already correct, so we no-op. runAssembly
// picks the beats it finds via [data-assembly] and skips the rest, so a row
// only needs whichever scaffold elements it renders.
export function useAssembly<T extends HTMLElement>(index = 0) {
  const ref = useRef<T | null>(null);
  useEffect(() => {
    if (!ref.current) return;
    const m = document.documentElement.dataset.motion;
    const reduced =
      m === "reduced" ||
      (m !== "full" &&
        typeof window !== "undefined" &&
        !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
    if (reduced) return; // final state renders instantly — no animation
    return runAssembly(ref.current, index);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return ref;
}
