"use client";

import type { ActivityEntry } from "@/lib/types";
import { kindRegister, relativeTime } from "@/lib/pulse";
import { useAssembly } from "@/lib/useAssembly";

interface Props {
  entry: ActivityEntry;
  // A row that points at a module/page is a button — tapping it closes the
  // panel and takes you to what the automation touched ("see what it made").
  onNavigate?: (target: { moduleId?: string | null; pageId?: string | null }) => void;
  // The panel's open-time clock, captured once — keeps this component pure
  // (no impure Date.now() during render) and every row's "ago" consistent.
  now: number;
  index: number;
}

// One journal line: a status dot + the mono uppercase register (from
// lib/pulse.kindRegister — the single source of truth) + the frozen summary +
// relative time. Rows construct in via lib/assembly (seed → label wipe → body
// rise); reduced motion renders the finished row instantly.
export function ActivityRow({ entry, onNavigate, now, index }: Props) {
  const ref = useAssembly<HTMLElement>(index);
  const reg = kindRegister(entry.kind);
  const label =
    entry.kind === "approved" && entry.simulated ? `${reg.label} · SIMULATED` : reg.label;
  const linked = !!(entry.module_id || entry.page_id);
  const when = relativeTime(entry.created_at, now);

  const inner = (
    <>
      <span
        aria-hidden
        className="mt-1 shrink-0 w-1.5 h-1.5 rounded-full"
        style={{ background: reg.colorToken }}
      />
      <div data-assembly="body" className="min-w-0 flex-1 flex flex-col gap-0.5">
        <span
          data-assembly="label"
          className="font-mono text-[10px] uppercase tracking-wide"
          style={{ color: reg.colorToken }}
        >
          {label}
        </span>
        <span className="text-sm text-[var(--foreground)] leading-snug break-words">
          {entry.summary}
        </span>
        {when && <span className="font-mono text-[10px] text-[var(--muted)]">{when}</span>}
      </div>
    </>
  );

  if (linked) {
    return (
      <button
        ref={ref as React.RefObject<HTMLButtonElement | null>}
        type="button"
        onClick={() => onNavigate?.({ moduleId: entry.module_id, pageId: entry.page_id })}
        className="w-full text-left flex items-start gap-2.5 rounded-lg px-2 py-2 hover:bg-[var(--surface-elevated)] transition-colors"
        title="Open what this touched"
      >
        {inner}
      </button>
    );
  }
  return (
    <div ref={ref as React.RefObject<HTMLDivElement | null>} className="flex items-start gap-2.5 rounded-lg px-2 py-2">
      {inner}
    </div>
  );
}
