"use client";

import { useEffect, useRef, useState } from "react";

interface Props {
  count: number;
  onOpen: () => void;
}

// The can't-miss home indicator (TAP-4). Rendered NOWHERE at 0 — absence is the
// calm state. At > 0 it is the home screen's single magenta accent: a fixed
// filled-magenta Geist Mono pill "N NEED YOUR TAP" that opens Pulse. One
// scale-settle pulse fires when the count climbs (reduced motion → static via
// the global rule). aria-live announces changes to screen readers.
export function ApprovalBadge({ count, onOpen }: Props) {
  const prev = useRef(count);
  const [pulse, setPulse] = useState(false);

  useEffect(() => {
    if (count > prev.current) {
      setPulse(true);
      const t = window.setTimeout(() => setPulse(false), 280);
      prev.current = count;
      return () => window.clearTimeout(t);
    }
    prev.current = count;
  }, [count]);

  if (count <= 0) return null;

  return (
    <button
      type="button"
      onClick={onOpen}
      aria-live="polite"
      aria-label={`${count} ${count === 1 ? "approval needs" : "approvals need"} your tap — open Pulse`}
      className={`press fixed top-16 right-4 z-30 rounded-full bg-[var(--accent)] text-[var(--accent-fg)] font-mono text-[11px] uppercase tracking-wide px-3 py-1.5 shadow-lg hover:brightness-110 transition ${
        pulse ? "animate-checkpop" : ""
      }`}
      style={{ boxShadow: "var(--accent-blue-glow)" }}
    >
      {count} need your tap
    </button>
  );
}
