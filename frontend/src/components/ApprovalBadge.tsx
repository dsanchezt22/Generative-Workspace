"use client";

import { useEffect, useRef, useState } from "react";

interface Props {
  count: number;
  onOpen: () => void;
}

// The can't-miss home indicator (TAP-4). Rendered NOWHERE at 0 — absence is the
// calm state. At > 0 it rides Pulse's amber "needs your tap" channel (§2 color
// law: the one filled magenta on the home canvas is the PromptBar CTA, so this
// must not be a second one): a fixed --status-hold Geist Mono pill on a
// --status-hold-dim fill, "N need your tap", that opens Pulse. One scale-settle
// pulse fires when the count climbs (reduced motion → static via the global
// rule). aria-live announces changes to screen readers.
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
      className={`press fixed top-16 right-4 z-30 rounded-full bg-[var(--status-hold-dim)] text-[var(--status-hold)] border border-[var(--status-hold)] font-mono text-[11px] uppercase tracking-wide px-3 py-1.5 shadow-lg transition ${
        pulse ? "animate-checkpop" : ""
      }`}
    >
      {count} need your tap
    </button>
  );
}
