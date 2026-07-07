"use client";

import { useState } from "react";
import type { ListField } from "@/lib/types";

interface Props {
  spec: ListField;
  value: string[];
  onChange: (v: string[]) => void;
}

export function ListFieldComponent({ spec, value, onChange }: Props) {
  const [draft, setDraft] = useState("");
  const items = Array.isArray(value) ? value : [];

  const add = () => {
    const v = draft.trim();
    if (!v) return;
    onChange([...items, v]);
    setDraft("");
  };

  const removeAt = (i: number) => onChange(items.filter((_, idx) => idx !== i));

  return (
    <div className="flex flex-col gap-2">
      <span className="text-xs uppercase tracking-wide text-[var(--muted)]">
        {spec.label}
      </span>
      <ul className="flex flex-col gap-1">
        {items.map((it, i) => (
          <li
            key={i}
            className="flex items-center justify-between gap-2 rounded-md bg-[var(--surface-elevated)] px-3 py-1.5 text-sm"
          >
            <span className="truncate">{it}</span>
            <button
              type="button"
              onClick={() => removeAt(i)}
              className="text-[var(--muted)] hover:text-[var(--danger)] transition-colors text-xs"
              aria-label={`Remove ${it}`}
            >
              ×
            </button>
          </li>
        ))}
        {items.length === 0 && (
          <li className="text-xs text-[var(--muted)] italic">
            No {spec.item_label.toLowerCase()}s yet.
          </li>
        )}
      </ul>
      <div className="flex gap-1.5">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          placeholder={spec.placeholder ?? `Add ${spec.item_label.toLowerCase()}…`}
          className="flex-1 rounded-md border border-[var(--border)] bg-[var(--surface-elevated)] px-3 py-1.5 text-sm placeholder:text-[var(--muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40"
        />
        <button
          type="button"
          onClick={add}
          className="rounded-md bg-[var(--accent)] text-[var(--accent-fg)] px-3 py-1.5 text-sm font-medium hover:bg-[var(--accent-hover)] transition"
        >
          Add
        </button>
      </div>
    </div>
  );
}
