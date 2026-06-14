"use client";

import type { Dropdown } from "@/lib/types";

interface Props {
  spec: Dropdown;
  value: string;
  onChange: (v: string) => void;
}

export function DropdownField({ spec, value, onChange }: Props) {
  const opts = spec.options ?? [];
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs uppercase tracking-wide text-[var(--muted)]">{spec.label}</span>
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-[var(--border)] bg-[var(--surface-elevated)] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40"
      >
        <option value="">Select…</option>
        {opts.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </div>
  );
}
