"use client";

import type { DatePicker } from "@/lib/types";

interface Props {
  spec: DatePicker;
  value: string;
  onChange: (v: string) => void;
}

export function DateField({ spec, value, onChange }: Props) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs uppercase tracking-wide text-[var(--muted)]">{spec.label}</span>
      <input
        type={spec.include_time ? "datetime-local" : "date"}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-sm border border-[var(--border)] bg-[var(--surface-elevated)] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40"
      />
    </div>
  );
}
