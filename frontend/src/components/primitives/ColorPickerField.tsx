"use client";

import type { ColorField } from "@/lib/types";

const SWATCHES = ["#d9a86c", "#84c89a", "#8fbce0", "#e0a0b4", "#c0a3e0", "#e8a285", "#7fccc0", "#d8c878", "#2b2825"];

interface Props {
  spec: ColorField;
  value: string;
  onChange: (v: string) => void;
}

export function ColorPickerField({ spec, value, onChange }: Props) {
  const current = value || "#84c89a";
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs uppercase tracking-wide text-[var(--muted)]">{spec.label}</span>
      <div className="flex items-center gap-2 flex-wrap">
        <input
          type="color"
          value={current}
          onChange={(e) => onChange(e.target.value)}
          className="w-8 h-8 rounded-sm border border-[var(--border)] bg-transparent cursor-pointer"
          aria-label={`${spec.label} colour`}
        />
        {SWATCHES.map((c) => (
          <button key={c} type="button" onClick={() => onChange(c)}
            className="w-5 h-5 rounded-full transition hover:scale-110"
            style={{ background: c, outline: value === c ? "2px solid var(--foreground)" : "none", outlineOffset: "1px" }}
            aria-label={`Pick ${c}`} />
        ))}
        <span className="text-xs text-[var(--muted)] font-mono">{current}</span>
      </div>
    </div>
  );
}
