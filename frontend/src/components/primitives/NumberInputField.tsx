"use client";

import type { NumberInput } from "@/lib/types";

interface Props {
  spec: NumberInput;
  value: number | "";
  onChange: (v: number | "") => void;
}

export function NumberInputField({ spec, value, onChange }: Props) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs uppercase tracking-wide text-[var(--muted)]">
        {spec.label}
        {spec.unit ? (
          <span className="ml-1 normal-case tracking-normal">({spec.unit})</span>
        ) : null}
      </span>
      <input
        type="number"
        value={value === undefined || value === null ? "" : value}
        min={spec.min ?? undefined}
        max={spec.max ?? undefined}
        step={spec.step ?? undefined}
        onChange={(e) =>
          onChange(e.target.value === "" ? "" : Number(e.target.value))
        }
        className="rounded-sm border border-[var(--border)] bg-[var(--surface-elevated)] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40"
      />
    </label>
  );
}
