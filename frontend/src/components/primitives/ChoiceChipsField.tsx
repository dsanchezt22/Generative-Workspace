"use client";

import type { ChoiceChips } from "@/lib/types";

interface Props {
  spec: ChoiceChips;
  value: string;
  onChange: (v: string) => void;
}

export function ChoiceChipsField({ spec, value, onChange }: Props) {
  const opts = spec.options ?? [];
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs uppercase tracking-wide text-[var(--muted)]">{spec.label}</span>
      <div className="flex flex-wrap gap-1.5">
        {opts.map((o) => {
          const on = value === o;
          return (
            <button
              key={o}
              type="button"
              onClick={() => onChange(on ? "" : o)}
              className="rounded-full px-3 py-1 text-xs border transition"
              style={{
                background: on ? "var(--accent)" : "transparent",
                color: on ? "var(--accent-fg)" : "var(--foreground)",
                borderColor: on ? "var(--accent)" : "var(--border)",
              }}
            >
              {o}
            </button>
          );
        })}
        {opts.length === 0 && <span className="text-xs text-[var(--muted)] italic">No options yet. Add some in the inspector.</span>}
      </div>
    </div>
  );
}
