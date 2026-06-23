"use client";

import type { TextInput } from "@/lib/types";

interface Props {
  spec: TextInput;
  value: string;
  onChange: (v: string) => void;
}

export function TextInputField({ spec, value, onChange }: Props) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs uppercase tracking-wide text-[var(--muted)]">
        {spec.label}
      </span>
      <input
        type="text"
        placeholder={spec.placeholder ?? ""}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-sm border border-[var(--border)] bg-[var(--surface-elevated)] px-3 py-2 text-sm placeholder:text-[var(--muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40"
      />
    </label>
  );
}
