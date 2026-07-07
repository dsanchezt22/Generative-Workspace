"use client";

import { useState } from "react";
import type { AutomationOut } from "@/lib/types";

interface Props {
  automation: AutomationOut;
  // Persists the new dial (api.patchAutomation). Rejects → the dial reverts and
  // shows an inline error register. Resolves → the parent adopts the returned row.
  onChange: (dial: number) => Promise<void>;
}

const STOPS: { dial: number; label: string }[] = [
  { dial: 0, label: "Ask always" },
  { dial: 1, label: "Standard" },
  { dial: 2, label: "Trusted" },
];

// The plain-language effect line, derived from the floor + dial — so the dial
// never leaves the owner guessing what it actually changed.
function effectLine(tierFloor: string, dial: number, irreversible: boolean): string {
  if (dial <= 0) return "Asks before doing anything.";
  if (tierFloor === "autonomous") return "Runs on its own; asks before anything consequential.";
  // consequential floor
  if (irreversible) return "Always asks before doing this — it can't be undone.";
  if (dial >= 2) return "Runs on its own now that you trust it.";
  return "Asks before doing this.";
}

// A 3-stop segmented control bound to trust_dial (0 ask-always · 1 standard · 2
// trusted). Optimistic: the stop selects instantly, the PATCH lands in the
// background, a failure reverts. For irreversible actions the Trusted stop still
// selects (0 vs 1 still matters) but a hard-floor lock line makes AUT-4 legible
// rather than hiding it.
export function TrustDial({ automation, onChange }: Props) {
  const [dial, setDial] = useState(automation.trust_dial);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const pick = async (next: number) => {
    if (next === dial || saving) return;
    const prev = dial;
    setDial(next); // optimistic
    setError(null);
    setSaving(true);
    try {
      await onChange(next);
    } catch {
      setDial(prev); // revert
      setError("Couldn't save that — try again.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-1.5">
      <div
        role="radiogroup"
        aria-label="Trust level"
        className="inline-flex rounded-md border border-[var(--border)] bg-[var(--surface)] p-0.5 self-start"
      >
        {STOPS.map((s) => {
          const active = s.dial === dial;
          return (
            <button
              key={s.dial}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => pick(s.dial)}
              className={`rounded px-2.5 py-1 text-[11px] font-medium transition ${
                active
                  ? "bg-[var(--surface-elevated)] text-[var(--foreground)]"
                  : "text-[var(--muted)] hover:text-[var(--foreground)]"
              }`}
            >
              {s.label}
            </button>
          );
        })}
      </div>

      <p className="text-[11px] text-[var(--muted)] leading-snug">
        {effectLine(automation.tier_floor, dial, automation.irreversible)}
      </p>

      {automation.irreversible && (
        <p className="font-mono text-[9px] uppercase tracking-wide text-[var(--muted)] flex items-start gap-1">
          <span aria-hidden>🔒</span>
          <span>Real-world actions (send, pay, delete) always ask you — hard floor</span>
        </p>
      )}

      {error && (
        <p className="font-mono text-[10px] uppercase tracking-wide text-[var(--danger)]">{error}</p>
      )}
    </div>
  );
}
