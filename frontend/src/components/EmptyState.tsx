"use client";

import { Icon } from "./Icon";

const CHIPS: [string, string][] = [
  ["Habit tracker", "Create a habit tracker"],
  ["Budget", "Create a monthly budget tracker"],
  ["Reading list", "Create a reading list"],
  ["Workout log", "Create a workout log"],
  ["Meal planner", "Create a weekly meal planner"],
];

export function EmptyState({ onPick }: { onPick: (text: string) => void }) {
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
          {CHIPS.map(([label, prompt]) => (
            <button
              key={label}
              type="button"
              onClick={() => onPick(prompt)}
              className="rounded-full border border-[var(--border)] bg-[var(--surface)] px-3 py-1.5 text-xs hover:border-[var(--accent)] hover:text-[var(--accent)] transition"
            >
              {label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
