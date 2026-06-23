"use client";

import type { Note } from "@/lib/types";

interface Props {
  spec: Note;
  value: string;
  onChange: (v: string) => void;
}

export function NoteField({ spec, value, onChange }: Props) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs uppercase tracking-wide text-[var(--muted)]">{spec.label}</span>
      <textarea
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        placeholder={spec.placeholder ?? "Write…"}
        rows={4}
        className="resize-y min-h-[5rem] rounded-sm border border-[var(--border)] bg-[var(--surface-elevated)] px-3 py-2 text-sm leading-relaxed placeholder:text-[var(--muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40"
      />
    </div>
  );
}
