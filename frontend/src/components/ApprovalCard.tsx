"use client";

import { useState } from "react";
import type { ApprovalItem } from "@/lib/pulse";
import { useAssembly } from "@/lib/useAssembly";

interface Props {
  item: ApprovalItem;
  onApprove: () => void;
  onDismiss: () => void;
  // The panel's open-time clock (captured once) — keeps this component pure.
  now: number;
  index: number;
}

// EXPIRES register — muted, honest. Frozen expiry from the server; we only
// phrase the remaining window ("expires in 2d" / "expires soon" / "expired").
function expiresRegister(iso: string, now: number): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const diff = t - now;
  if (diff <= 0) return "expired";
  const hours = diff / 3_600_000;
  if (hours < 1) return "expires soon";
  if (hours < 24) return `expires in ${Math.floor(hours)}h`;
  return `expires in ${Math.floor(hours / 24)}d`;
}

// A parked consequential fire, waiting for the owner's tap. Shows the frozen
// server summary (never re-composed client-side), a mono action-type chip, an
// expandable typed preview (the exact bytes that will run), and the two
// decisions. Approve is the panel's ONE filled-magenta button; Dismiss is a
// ghost. The tap flow is optimistic and honest: in-flight shows EXECUTING…, a
// 5xx restores the buttons with a FAILED register — nothing pretends success.
export function ApprovalCard({ item, onApprove, onDismiss, now, index }: Props) {
  const ref = useAssembly<HTMLDivElement>(index);
  const [expanded, setExpanded] = useState(false);
  const { approval, pending, error } = item;
  const preview = approval.preview;
  const busy = pending !== null;
  const expires = expiresRegister(approval.expires_at, now);

  return (
    <div
      ref={ref}
      className={`relative overflow-hidden rounded-2xl border bg-[var(--surface-elevated)] p-3 flex flex-col gap-2.5 ${
        error ? "border-[var(--danger)]" : "border-[var(--border)]"
      } ${busy ? "opacity-70" : ""}`}
    >
      {/* Assembly scaffold — border traces, a light band sweeps (ethos §5.2). */}
      <svg
        data-assembly="border-svg"
        className="pointer-events-none absolute inset-0 z-20 opacity-0"
        preserveAspectRatio="none"
        aria-hidden
      >
        <rect data-assembly="border" fill="none" stroke="var(--accent)" strokeWidth="1.5" rx="16" ry="16" />
      </svg>
      <div className="pointer-events-none absolute inset-0 z-20 overflow-hidden rounded-2xl" aria-hidden>
        <div
          data-assembly="scan"
          className="absolute inset-y-0 left-0 w-1/2 opacity-0"
          style={{
            background:
              "linear-gradient(100deg, transparent 20%, color-mix(in srgb, var(--white-matte) 28%, transparent) 50%, transparent 80%)",
          }}
        />
      </div>

      <div data-assembly="body" className="flex flex-col gap-2.5">
        <div className="flex items-start gap-2">
          <p data-assembly="label" className="flex-1 text-sm text-[var(--foreground)] leading-snug">
            {approval.summary}
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-mono text-[10px] uppercase tracking-wide text-[var(--muted)] rounded bg-[var(--surface)] border border-[var(--border)] px-1.5 py-0.5">
            {approval.action_type}
          </span>
          {expires && (
            <span className="font-mono text-[10px] uppercase tracking-wide text-[var(--muted)]">
              {expires}
            </span>
          )}
          {preview && (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="ml-auto font-mono text-[10px] uppercase tracking-wide text-[var(--muted)] hover:text-[var(--foreground)] transition"
              aria-expanded={expanded}
            >
              {expanded ? "hide details" : "details"}
            </button>
          )}
        </div>

        {expanded && preview && (
          <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-2.5 flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold tracking-tight">{preview.title}</span>
              {preview.simulated && (
                <span className="font-mono text-[9px] uppercase tracking-wide text-[var(--status-hold)] bg-[var(--status-hold-dim)] rounded px-1.5 py-0.5">
                  simulated
                </span>
              )}
            </div>
            {preview.fields.length > 0 && (
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                {preview.fields.map((f, i) => (
                  <div key={i} className="contents">
                    <dt className="font-mono text-[10px] uppercase tracking-wide text-[var(--muted)] py-0.5">
                      {f.label}
                    </dt>
                    <dd className="text-xs text-[var(--foreground)] break-words py-0.5">{f.value}</dd>
                  </div>
                ))}
              </dl>
            )}
            {preview.body && (
              <pre className="font-mono text-[11px] leading-relaxed text-[var(--foreground)] whitespace-pre-wrap break-words bg-[var(--surface-elevated)] rounded-md p-2 border border-[var(--border)]">
                {preview.body}
              </pre>
            )}
          </div>
        )}

        {error && (
          <p className="font-mono text-[10px] uppercase tracking-wide text-[var(--danger)]">
            failed — {error}
          </p>
        )}

        <div className="flex items-center gap-2 pt-0.5">
          <button
            type="button"
            onClick={onApprove}
            disabled={busy}
            className="press rounded-md bg-[var(--accent)] text-[var(--accent-fg)] px-3 py-1.5 text-xs font-medium hover:bg-[var(--accent-hover)] transition disabled:opacity-60 disabled:cursor-wait"
          >
            {pending === "approve" ? "Executing…" : "Approve"}
          </button>
          <button
            type="button"
            onClick={onDismiss}
            disabled={busy}
            className="rounded-md border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--muted)] hover:text-[var(--foreground)] transition disabled:opacity-60 disabled:cursor-wait"
          >
            {pending === "reject" ? "Dismissing…" : "Dismiss"}
          </button>
        </div>
      </div>
    </div>
  );
}
