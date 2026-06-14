"use client";

import { useState } from "react";
import type { Gallery } from "@/lib/types";

interface Props {
  spec: Gallery;
  value: string[];
  onChange: (v: string[]) => void;
}

export function GalleryField({ spec, value, onChange }: Props) {
  const imgs = Array.isArray(value) ? value : [];
  const [draft, setDraft] = useState("");

  const add = () => {
    const u = draft.trim();
    if (!u) return;
    onChange([...imgs, u]);
    setDraft("");
  };

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs uppercase tracking-wide text-[var(--muted)]">{spec.label}</span>
      {imgs.length > 0 && (
        <div className="grid grid-cols-3 gap-1.5">
          {imgs.map((src, i) => (
            <div key={i} className="group relative aspect-square rounded-md overflow-hidden bg-[var(--surface-elevated)]">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={src} alt="" className="w-full h-full object-cover" onError={(e) => { (e.target as HTMLImageElement).style.opacity = "0"; }} />
              <button type="button" onClick={() => onChange(imgs.filter((_, idx) => idx !== i))}
                className="absolute top-1 right-1 w-5 h-5 rounded-full bg-black/50 text-white text-xs grid place-items-center opacity-0 group-hover:opacity-100" aria-label="Remove image">×</button>
            </div>
          ))}
        </div>
      )}
      <div className="flex gap-1.5">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
          placeholder="Paste image URL…"
          className="flex-1 min-w-0 rounded-md border border-[var(--border)] bg-[var(--surface-elevated)] px-2.5 py-1.5 text-sm placeholder:text-[var(--muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40"
        />
        <button type="button" onClick={add} className="rounded-md bg-[var(--accent)] text-[var(--accent-fg)] px-3 py-1.5 text-sm font-medium hover:brightness-110 transition">Add</button>
      </div>
    </div>
  );
}
