"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { filterSuggestions, suggestionLabel } from "@/lib/suggestions";
import { Icon } from "./Icon";

// R-104 fallback: the hand-written starter chips for a brand-new owner (no usage
// history yet) or when the suggestions fetch is empty / errors.
const STATIC_CHIPS: [string, string][] = [
  ["Habit tracker", "Create a habit tracker"],
  ["Budget", "Create a monthly budget tracker"],
  ["Reading list", "Create a reading list"],
  ["Workout log", "Create a workout log"],
  ["Meal planner", "Create a weekly meal planner"],
];

export function EmptyState({
  onPick,
  onStartConversation,
}: {
  onPick: (text: string) => void;
  onStartConversation?: () => void;
}) {
  // [label, prompt] pairs. Starts as the static fallback; replaced by usage-seeded
  // suggestions once they load (R-104). Never goes empty — a failed/empty fetch
  // keeps the static chips.
  const [chips, setChips] = useState<[string, string][]>(STATIC_CHIPS);

  useEffect(() => {
    let alive = true;
    api
      .suggestions(6)
      .then((rows) => {
        if (!alive) return;
        // Filter file-log lines / terse fragments / refine instructions, then
        // map surviving build prompts to [shortLabel, fullPrompt] chips.
        const clean = filterSuggestions(rows.map((r) => r.prompt));
        if (clean.length) setChips(clean.map((p) => [suggestionLabel(p), p]));
        // else: keep the static fallback already in state.
      })
      .catch(() => {
        /* keep the static fallback */
      });
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="absolute inset-0 grid place-items-center pointer-events-none px-6">
      <div className="pointer-events-auto flex flex-col items-center gap-4 -mt-20 text-center max-w-md">
        <div className="w-12 h-12 rounded-2xl bg-[var(--surface-elevated)] border border-[var(--border)] grid place-items-center text-[var(--accent)] animate-pop">
          <Icon name="sparkles" size={24} />
        </div>
        <h2 className="text-lg font-semibold tracking-tight">What do you want to organize?</h2>
        <p className="text-sm text-[var(--muted)] leading-relaxed">
          Describe a tool in a sentence and it appears — a tracker, planner, log,
          or list. Or start with one of these:
        </p>
        <div className="flex flex-wrap justify-center gap-2">
          {chips.map(([label, prompt]) => (
            <button
              key={prompt}
              type="button"
              onClick={() => onPick(prompt)}
              className="rounded-full border border-[var(--border)] bg-[var(--surface)] px-3 py-1.5 text-xs hover:border-[var(--accent)] hover:text-[var(--accent)] transition"
            >
              {label}
            </button>
          ))}
        </div>
        {onStartConversation && (
          <button
            type="button"
            onClick={onStartConversation}
            className="mt-1 flex items-center gap-1.5 text-xs text-[var(--muted)] hover:text-[var(--foreground)] transition"
          >
            <Icon name="mic" size={13} />
            Start with a conversation
          </button>
        )}
      </div>
    </div>
  );
}
