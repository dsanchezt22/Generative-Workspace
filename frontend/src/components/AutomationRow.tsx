"use client";

import { useState } from "react";
import type { AutomationOut } from "@/lib/types";
import { useAssembly } from "@/lib/useAssembly";
import { TrustDial } from "./TrustDial";

interface Props {
  automation: AutomationOut;
  onPatchDial: (dial: number) => Promise<void>;
  onToggle: () => Promise<void>;
  onRun: () => Promise<void>;
  onRequestDelete: () => void;
  index: number;
}

// The mono schedule register: "every 6h · next 14:02" / "daily at 07:00".
function scheduleRegister(a: AutomationOut): string {
  let base: string;
  if (a.schedule_kind === "daily" && a.daily_at) {
    base = `daily at ${a.daily_at}`;
  } else if (a.interval_secs) {
    const s = a.interval_secs;
    if (s % 86400 === 0) base = `every ${s / 86400}d`;
    else if (s % 3600 === 0) base = `every ${s / 3600}h`;
    else base = `every ${Math.round(s / 60)}m`;
  } else {
    base = "manual";
  }
  if (a.next_run_at) {
    const t = Date.parse(a.next_run_at);
    if (!Number.isNaN(t)) {
      const next = new Date(t).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
      return `${base} · next ${next}`;
    }
  }
  return base;
}

// One managed automation: name + tier chip, an enabled toggle, the schedule
// register, the TrustDial, Run now, and delete (delete is confirmed by the
// panel via a ConfirmDialog rendered as a SIBLING of the sliding aside — the
// containing-block lesson — so this row only requests it).
export function AutomationRow({
  automation,
  onPatchDial,
  onToggle,
  onRun,
  onRequestDelete,
  index,
}: Props) {
  const ref = useAssembly<HTMLDivElement>(index);
  const [running, setRunning] = useState(false);
  const [toggling, setToggling] = useState(false);

  const run = async () => {
    if (running) return;
    setRunning(true);
    try {
      await onRun();
    } finally {
      setRunning(false);
    }
  };

  const toggle = async () => {
    if (toggling) return;
    setToggling(true);
    try {
      await onToggle();
    } finally {
      setToggling(false);
    }
  };

  return (
    <div
      ref={ref}
      className="relative overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)] p-3 flex flex-col gap-2.5"
    >
      <svg
        data-assembly="border-svg"
        className="pointer-events-none absolute inset-0 z-20 opacity-0"
        preserveAspectRatio="none"
        aria-hidden
      >
        <rect data-assembly="border" fill="none" stroke="var(--accent)" strokeWidth="1.5" rx="12" ry="12" />
      </svg>

      <div data-assembly="body" className="flex flex-col gap-2.5">
        <div className="flex items-center gap-2">
          <span data-assembly="label" className="text-sm font-medium truncate flex-1" title={automation.name}>
            {automation.name}
          </span>
          <span className="font-mono text-[9px] uppercase tracking-wide text-[var(--muted)] rounded bg-[var(--surface)] border border-[var(--border)] px-1.5 py-0.5 shrink-0">
            {automation.tier_floor}
          </span>
          {/* Enabled toggle — a small switch, muted (not the panel's magenta). */}
          <button
            type="button"
            role="switch"
            aria-checked={automation.enabled}
            aria-label={automation.enabled ? "Disable automation" : "Enable automation"}
            onClick={toggle}
            disabled={toggling}
            className={`shrink-0 w-8 h-[18px] rounded-full p-0.5 transition-colors disabled:opacity-50 ${
              automation.enabled ? "bg-[var(--status-ok)]" : "bg-[var(--border-strong)]"
            }`}
          >
            <span
              className="block w-3.5 h-3.5 rounded-full bg-[var(--white-matte)] transition-transform"
              style={{ transform: automation.enabled ? "translateX(14px)" : "translateX(0)" }}
            />
          </button>
        </div>

        <div className="font-mono text-[10px] text-[var(--muted)] tracking-wide">
          {scheduleRegister(automation)}
        </div>

        <TrustDial automation={automation} onChange={onPatchDial} />

        <div className="flex items-center gap-2 pt-0.5">
          <button
            type="button"
            onClick={run}
            disabled={running}
            className="rounded-md border border-[var(--border)] px-2.5 py-1 text-[11px] text-[var(--muted)] hover:text-[var(--foreground)] transition disabled:opacity-60 disabled:cursor-wait"
          >
            {running ? "Running…" : "Run now"}
          </button>
          <button
            type="button"
            onClick={onRequestDelete}
            aria-label="Delete automation"
            className="ml-auto text-[11px] text-[var(--muted)] hover:text-[var(--danger)] transition"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}
