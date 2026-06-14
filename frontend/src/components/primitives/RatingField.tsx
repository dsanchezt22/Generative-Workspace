"use client";

import type { Rating } from "@/lib/types";

interface Props {
  spec: Rating;
  value: number;
  onChange: (v: number) => void;
}

export function RatingField({ spec, value, onChange }: Props) {
  const max = spec.max ?? 5;
  const current = Number(value) || 0;
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs uppercase tracking-wide text-[var(--muted)]">{spec.label}</span>
      <div className="flex gap-1">
        {Array.from({ length: max }, (_, i) => i + 1).map((n) => (
          <button
            key={n}
            type="button"
            onClick={() => onChange(n === current ? 0 : n)}
            className="text-xl leading-none transition hover:scale-110"
            style={{ color: n <= current ? "var(--accent)" : "var(--border)" }}
            aria-label={`Rate ${n}`}
          >
            ★
          </button>
        ))}
        <span className="ml-1 self-center text-xs text-[var(--muted)] tabular-nums">{current}/{max}</span>
      </div>
    </div>
  );
}
