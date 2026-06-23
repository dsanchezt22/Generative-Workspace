"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Icon } from "./Icon";

export interface SelectOption {
  value: string;
  label: string;
}

interface Props {
  value: string;
  options: SelectOption[];
  onChange: (v: string) => void;
  className?: string;
  ariaLabel?: string;
}

// On-theme dropdown. The menu renders in a fixed-position layer so it's never
// clipped by a scrolling panel, and looks identical in light/dark.
export function Select({ value, options, onChange, className, ariaLabel }: Props) {
  const [open, setOpen] = useState(false);
  const btnRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [rect, setRect] = useState<{ top: number; left: number; width: number } | null>(null);

  const current = options.find((o) => o.value === value);

  const place = () => {
    const r = btnRef.current?.getBoundingClientRect();
    if (r) setRect({ top: r.bottom + 4, left: r.left, width: r.width });
  };

  useLayoutEffect(() => { if (open) place(); }, [open]);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (btnRef.current?.contains(e.target as Node) || menuRef.current?.contains(e.target as Node)) return;
      setOpen(false);
    };
    // Close when the page/panel scrolls (the fixed menu would otherwise detach
    // from its button) — but NOT when the menu's own option list scrolls, so
    // long dropdowns stay open while you scroll to a lower option.
    const onScroll = (e: Event) => {
      if (menuRef.current?.contains(e.target as Node)) return;
      setOpen(false);
    };
    const onResize = () => setOpen(false);
    document.addEventListener("mousedown", close);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onResize);
    return () => {
      document.removeEventListener("mousedown", close);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onResize);
    };
  }, [open]);

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
        aria-label={ariaLabel}
        className={`flex items-center justify-between gap-1.5 rounded-sm border border-[var(--border)] bg-[var(--surface)] px-2 py-1 text-xs text-[var(--foreground)] hover:border-[var(--accent)] transition ${className ?? ""}`}
      >
        <span className="truncate">{current?.label ?? "Select…"}</span>
        <Icon name="chevronDown" size={12} className="text-[var(--muted)] shrink-0" />
      </button>
      {open && rect && (
        <div
          ref={menuRef}
          className="fixed z-[70] rounded-lg border border-[var(--border)] bg-[var(--surface)] shadow-2xl shadow-black/30 py-1 max-h-64 overflow-y-auto animate-scale-in"
          style={{ top: rect.top, left: rect.left, minWidth: Math.max(rect.width, 120) }}
          onMouseDown={(e) => e.stopPropagation()}
        >
          {options.map((o) => (
            <button
              key={o.value}
              type="button"
              onClick={() => { onChange(o.value); setOpen(false); }}
              className={`w-full text-left px-3 py-1.5 text-xs transition hover:bg-[var(--surface-elevated)] ${
                o.value === value ? "text-[var(--accent)] font-medium" : "text-[var(--foreground)]"
              }`}
            >
              {o.label}
            </button>
          ))}
        </div>
      )}
    </>
  );
}
