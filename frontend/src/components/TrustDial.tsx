"use client";

import { useRef, useState } from "react";
import type { AutomationOut } from "@/lib/types";
import { Icon } from "./Icon";

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
  // Trusted (dial 2) unlocks only the reversible-consequential span today —
  // archiving on its own — while the hard floor (send / pay / delete) always asks.
  if (dial >= 2) return "Archives on its own; still asks before send, pay, or delete.";
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
  // Roving tabindex targets: only the checked stop is tabbable; the arrow keys
  // move focus + selection across the group (WAI-ARIA radiogroup contract).
  const btnRefs = useRef<(HTMLButtonElement | null)[]>([]);

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

  // ArrowLeft/Up → previous stop, ArrowRight/Down → next (wrapping); each move
  // focuses AND selects the stop, matching a native radio group.
  const onKeyNav = (e: React.KeyboardEvent, i: number) => {
    let ni: number | null = null;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") ni = (i + 1) % STOPS.length;
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") ni = (i - 1 + STOPS.length) % STOPS.length;
    if (ni === null) return;
    e.preventDefault();
    btnRefs.current[ni]?.focus();
    void pick(STOPS[ni].dial);
  };

  return (
    <div className="flex flex-col gap-1.5">
      <div
        role="radiogroup"
        aria-label="Trust level"
        className="inline-flex rounded-md border border-[var(--border)] bg-[var(--surface)] p-0.5 self-start"
      >
        {STOPS.map((s, i) => {
          const active = s.dial === dial;
          return (
            <button
              key={s.dial}
              ref={(el) => { btnRefs.current[i] = el; }}
              type="button"
              role="radio"
              aria-checked={active}
              tabIndex={active ? 0 : -1}
              onClick={() => pick(s.dial)}
              onKeyDown={(e) => onKeyNav(e, i)}
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
          <Icon name="lock" size={10} className="mt-[1px] shrink-0" />
          <span>Real-world actions (send, pay, delete) always ask you — hard floor</span>
        </p>
      )}

      {error && (
        <p className="font-mono text-[10px] uppercase tracking-wide text-[var(--danger)]">{error}</p>
      )}
    </div>
  );
}
