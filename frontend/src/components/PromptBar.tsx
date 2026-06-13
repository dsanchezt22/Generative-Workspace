"use client";

import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { StoredModule } from "@/lib/types";

interface Props {
  onModule: (m: StoredModule) => void;
  refineTarget?: StoredModule | null;
  onRefineModule?: (m: StoredModule) => void;
  onClearRefine?: () => void;
}

export function PromptBar({ onModule, refineTarget, onRefineModule, onClearRefine }: Props) {
  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isRefining = Boolean(refineTarget);

  const submit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const v = prompt.trim();
    if (!v || loading) return;
    setLoading(true);
    setError(null);
    try {
      if (refineTarget && onRefineModule) {
        const updated = await api.refineModule(refineTarget.id, v);
        onRefineModule(updated);
      } else {
        const { module } = await api.generateModule(v);
        onModule(module);
      }
      setPrompt("");
    } catch (err) {
      if (err instanceof ApiError && err.refusal) {
        setError(err.refusal);
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Something went wrong.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <form
      onSubmit={submit}
      className="absolute left-1/2 -translate-x-1/2 bottom-6 w-[min(720px,calc(100%-2rem))] z-10"
    >
      <div className="flex flex-col rounded-2xl border border-[var(--border)] bg-[var(--surface)]/95 backdrop-blur shadow-2xl shadow-black/40 overflow-hidden">
        {isRefining && refineTarget && (
          <div className="flex items-center gap-2 px-4 pt-2.5 pb-0">
            <span className="text-[10px] uppercase tracking-wide text-[var(--muted)] font-mono">Refining</span>
            <span className="text-xs text-[var(--accent)] font-medium truncate max-w-[260px]">
              {refineTarget.config.title}
            </span>
            <button
              type="button"
              onClick={onClearRefine}
              className="ml-auto text-[var(--muted)] hover:text-[var(--foreground)] transition text-xs shrink-0"
              aria-label="Cancel refine"
            >
              ✕ cancel
            </button>
          </div>
        )}
        <div className="flex items-center gap-2 px-4 py-3">
          <input
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            disabled={loading}
            placeholder={
              isRefining
                ? "Describe what to change — e.g. add a rest day checkbox"
                : "Describe what you want to organize — e.g. track my workouts"
            }
            className="flex-1 bg-transparent text-sm placeholder:text-[var(--muted)] focus:outline-none disabled:opacity-50"
            autoFocus
          />
          <button
            type="submit"
            disabled={!prompt.trim() || loading}
            className="rounded-md bg-[var(--accent)] text-[var(--accent-fg)] px-3 py-1.5 text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:brightness-110 transition shrink-0"
          >
            {loading ? (isRefining ? "Refining…" : "Generating…") : isRefining ? "Refine" : "Generate"}
          </button>
        </div>
        {error && (
          <div className="px-4 pb-3 -mt-1">
            <div className="text-xs text-[var(--danger)]">{error}</div>
          </div>
        )}
      </div>
    </form>
  );
}
