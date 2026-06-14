"use client";

import { useEffect, useRef, useState } from "react";
import { useAppearance, type Density, type Motion, type Scale, type ThemeMode } from "@/lib/appearance";
import { ACCENTS, ACCENT_NAMES } from "@/lib/theme";
import { Icon } from "./Icon";

export function AppearanceMenu() {
  const { theme, density, accent, scale, motion, grid, setTheme, setDensity, setAccent, setScale, setMotion, setGrid } = useAppearance();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const seg =
    "flex-1 text-xs px-2 py-1 rounded-md transition capitalize";
  const segOn = "bg-[var(--accent)] text-[var(--accent-fg)]";
  const segOff = "text-[var(--muted)] hover:text-[var(--foreground)]";

  return (
    <div className="relative shrink-0" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-7 h-7 rounded-full bg-[var(--surface-elevated)] border border-[var(--border)] grid place-items-center text-xs text-[var(--muted)] hover:text-[var(--foreground)] transition"
        aria-label="Account & appearance"
        title="Account & appearance"
      >
        <Icon name="sliders" size={14} />
      </button>

      {open && (
        <div className="absolute right-0 top-9 z-40 w-60 rounded-xl border border-[var(--border)] bg-[var(--surface)] shadow-2xl shadow-black/30 p-3 flex flex-col gap-3">
          <div>
            <p className="text-[10px] uppercase tracking-wide text-[var(--muted)] mb-1.5">Theme</p>
            <div className="flex gap-1 rounded-lg bg-[var(--surface-elevated)] p-1">
              {(["light", "dark", "system"] as ThemeMode[]).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setTheme(t)}
                  className={`${seg} ${theme === t ? segOn : segOff}`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          <div>
            <p className="text-[10px] uppercase tracking-wide text-[var(--muted)] mb-1.5">Density</p>
            <div className="flex gap-1 rounded-lg bg-[var(--surface-elevated)] p-1">
              {(["comfortable", "compact"] as Density[]).map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => setDensity(d)}
                  className={`${seg} ${density === d ? segOn : segOff}`}
                >
                  {d}
                </button>
              ))}
            </div>
          </div>

          <div>
            <p className="text-[10px] uppercase tracking-wide text-[var(--muted)] mb-1.5">System accent</p>
            <div className="flex flex-wrap gap-1.5">
              <button
                type="button"
                onClick={() => setAccent("")}
                className="w-5 h-5 rounded-full border border-[var(--border)] grid place-items-center text-[10px] text-[var(--muted)]"
                style={{ outline: accent === "" ? "2px solid var(--foreground)" : "none", outlineOffset: "1px" }}
                aria-label="Default accent"
                title="Theme default"
              >
                ✕
              </button>
              {ACCENT_NAMES.map((name) => (
                <button
                  key={name}
                  type="button"
                  onClick={() => setAccent(name)}
                  className="w-5 h-5 rounded-full transition hover:scale-110"
                  style={{
                    background: ACCENTS[name].accent,
                    outline: accent === name ? "2px solid var(--foreground)" : "none",
                    outlineOffset: "1px",
                  }}
                  aria-label={`Accent ${name}`}
                  title={name}
                />
              ))}
            </div>
          </div>

          <div>
            <p className="text-[10px] uppercase tracking-wide text-[var(--muted)] mb-1.5">Text size</p>
            <div className="flex gap-1 rounded-lg bg-[var(--surface-elevated)] p-1">
              {(["s", "m", "l"] as Scale[]).map((s) => (
                <button key={s} type="button" onClick={() => setScale(s)} className={`${seg} ${scale === s ? segOn : segOff}`}>
                  {s === "s" ? "Small" : s === "m" ? "Medium" : "Large"}
                </button>
              ))}
            </div>
          </div>

          <div>
            <p className="text-[10px] uppercase tracking-wide text-[var(--muted)] mb-1.5">Motion</p>
            <div className="flex gap-1 rounded-lg bg-[var(--surface-elevated)] p-1">
              {(["system", "full", "reduced"] as Motion[]).map((m) => (
                <button key={m} type="button" onClick={() => setMotion(m)} className={`${seg} ${motion === m ? segOn : segOff}`}>{m}</button>
              ))}
            </div>
          </div>

          <div className="flex items-center justify-between">
            <p className="text-[10px] uppercase tracking-wide text-[var(--muted)]">Dotted grid</p>
            <button type="button" onClick={() => setGrid(!grid)} role="switch" aria-checked={grid}
              className={`relative w-9 h-5 rounded-full transition ${grid ? "bg-[var(--accent)]" : "bg-[var(--surface-elevated)] border border-[var(--border)]"}`}
              aria-label="Toggle dotted grid">
              <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${grid ? "translate-x-4" : ""}`} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
