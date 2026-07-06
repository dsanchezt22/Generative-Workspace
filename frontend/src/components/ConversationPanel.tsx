"use client";

import { useRef } from "react";
import type { Message } from "@/lib/types";
import { useDialog } from "@/lib/useDialog";

function timeAgo(iso: string): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const s = Math.floor((Date.now() - t) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

interface Props {
  messages: Message[];
  pageName: string;
  onClose: () => void;
  onClear: () => void;
  onReuse: (text: string) => void;
}

export function ConversationPanel({ messages, pageName, onClose, onClear, onReuse }: Props) {
  // R-1306 dialog floor (mount IS open — page.tsx renders this conditionally).
  // Initial focus lands on the ✕, NOT the first tabbable in DOM order — that's
  // "Clear", and Enter straight after opening must not wipe the history.
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const { ref: dialogRef, onKeyDown } = useDialog<HTMLElement>(true, onClose, closeRef);
  return (
    // R-1304: full-width sheet below `sm` (the fixed 320px column would
    // otherwise leave the canvas a sliver on a 375px phone) — same panel,
    // same tokens/animation, just full-bleed on a narrow viewport.
    <aside
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-label={`History — ${pageName}`}
      onKeyDown={onKeyDown}
      className="fixed top-0 inset-x-0 sm:inset-x-auto sm:right-0 h-screen w-full sm:w-[320px] sm:max-w-[85vw] z-30 bg-[var(--surface)] border-l border-[var(--border)] shadow-2xl shadow-black/40 flex flex-col animate-slide-right">
      <header className="flex items-center gap-2 px-4 h-14 border-b border-[var(--border)] shrink-0">
        <span className="text-sm font-semibold tracking-tight">History</span>
        <span className="text-xs text-[var(--muted)] truncate min-w-0">· {pageName}</span>
        <div className="ml-auto flex items-center gap-1 shrink-0">
          {messages.length > 0 && (
            <button
              type="button"
              onClick={onClear}
              className="text-xs text-[var(--muted)] hover:text-[var(--danger)] transition px-1.5 py-1 rounded"
              title="Clear this tab's history"
            >
              Clear
            </button>
          )}
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            className="text-[var(--muted)] hover:text-[var(--foreground)] transition w-6 h-6 grid place-items-center rounded"
            aria-label="Close history"
          >
            ✕
          </button>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-2">
        {messages.length === 0 ? (
          <p className="text-xs text-[var(--muted)] leading-relaxed px-1 pt-2">
            No prompts yet on this tab. Generate a tool and your prompts will be
            saved here — click any of them to run it again.
          </p>
        ) : (
          messages.map((m) =>
            m.role === "user" ? (
              <button
                key={m.id}
                type="button"
                onClick={() => onReuse(m.text)}
                className="text-left w-full rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] px-3 py-2 text-sm hover:border-[var(--accent)] transition"
                title="Reuse this prompt"
              >
                <span className="block text-[10px] uppercase tracking-wide text-[var(--muted)] mb-0.5">
                  You · {timeAgo(m.created_at)} · reuse ↵
                </span>
                <span className="break-words">{m.text}</span>
              </button>
            ) : (
              <div
                key={m.id}
                className="flex items-start gap-1.5 px-3 text-xs text-[var(--muted)]"
              >
                <span className="text-[var(--accent)] shrink-0">✓</span>
                <span className="break-words">{m.text}</span>
              </div>
            ),
          )
        )}
      </div>
    </aside>
  );
}
