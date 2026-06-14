"use client";

import { useState } from "react";
import type { Tags } from "@/lib/types";

interface Props {
  spec: Tags;
  value: string[];
  onChange: (v: string[]) => void;
}

export function TagsField({ spec, value, onChange }: Props) {
  const [draft, setDraft] = useState("");
  const tags = Array.isArray(value) ? value : [];

  const add = () => {
    const v = draft.trim();
    if (!v || tags.includes(v)) { setDraft(""); return; }
    onChange([...tags, v]);
    setDraft("");
  };

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs uppercase tracking-wide text-[var(--muted)]">{spec.label}</span>
      <div className="flex flex-wrap items-center gap-1.5">
        {tags.map((t, i) => (
          <span key={i} className="flex items-center gap-1 rounded-full px-2 py-0.5 text-xs"
            style={{ background: "color-mix(in srgb, var(--accent) 20%, transparent)" }}>
            {t}
            <button type="button" onClick={() => onChange(tags.filter((_, idx) => idx !== i))}
              className="text-[var(--muted)] hover:text-[var(--danger)]" aria-label={`Remove ${t}`}>×</button>
          </span>
        ))}
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
          onBlur={add}
          placeholder={spec.placeholder ?? "Add tag…"}
          className="flex-1 min-w-[80px] bg-transparent text-sm placeholder:text-[var(--muted)] focus:outline-none"
        />
      </div>
    </div>
  );
}
