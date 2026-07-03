"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { ModuleConfig, StoredModule } from "@/lib/types";
import { appendTranscript, formatElapsed } from "@/lib/voiceRamble";
import { useVoiceRamble } from "@/lib/useVoiceRamble";
import { Icon } from "./Icon";
import { Module } from "./Module";

const NOW = new Date().toISOString();
const noop = () => {};
const DEGRADED_NOTICE = "Offline fallback: built from a local template, not the AI model.";

interface Props {
  onModule: (m: StoredModule) => void;
  activePageId?: string;
  refineTarget?: StoredModule | null;
  onRefineModule?: (m: StoredModule) => void;
  onClearRefine?: () => void;
  seed?: string | null;
  onSeedConsumed?: () => void;
  focusSignal?: number;
  // R-101: a prompt handed over from the entry-screen front door — filled in
  // and auto-submitted once (produces a preview exactly like a typed prompt),
  // then cleared via onAutoPromptConsumed.
  autoPrompt?: string | null;
  onAutoPromptConsumed?: () => void;
}

interface ExchangeTurnState {
  question: string;
  answer: string;
}

// R-102: a multi-turn clarifying interview — the original prompt plus every
// question/answer pair so far (oldest first). The LAST turn's answer is ""
// until the user responds to it. Replaces the old originalPromptRef
// string-concat, which dropped every answer but the most recent.
interface Exchange {
  original: string;
  turns: ExchangeTurnState[];
}

const SKIP_ANSWER = "just build it — use your best judgment";

export function PromptBar({ onModule, activePageId, refineTarget, onRefineModule, onClearRefine, seed, onSeedConsumed, focusSignal, autoPrompt, onAutoPromptConsumed }: Props) {
  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Clarifying-interview state: when the AI needs one more answer before generating.
  const [exchange, setExchange] = useState<Exchange | null>(null);
  const pendingQuestion = exchange ? exchange.turns[exchange.turns.length - 1].question : null;
  // Clamped to 4: the backend hard-caps the chain (never a fifth question), so
  // the hint can never display a number beyond the "of 4" promise.
  const questionNumber = exchange ? Math.min(exchange.turns.length, 4) : 0;
  const inputRef = useRef<HTMLInputElement | null>(null);

  const isRefining = Boolean(refineTarget);
  const [file, setFile] = useState<File | null>(null);
  const [previews, setPreviews] = useState<ModuleConfig[]>([]);
  // R-103/R-301: the model's one-paragraph rationale for the current preview stack.
  const [plan, setPlan] = useState<string | null>(null);
  const lastPromptRef = useRef<string>("");
  const fileRef = useRef<HTMLInputElement | null>(null);

  // R-201-204: the shared ramble recorder. The hook owns all the browser
  // plumbing; PromptBar only decides what happens to a finished transcript —
  // append it (never overwrite, R-201) and auto-submit through the normal
  // submit() flow when the input was empty at record-start (R-202). Reusing
  // submit() means an in-progress interview/refine/preview is resolved
  // correctly instead of being clobbered by a bare preview call.
  const { voiceMode, recording, transcribing, elapsedSec, liveInterim, toggleMic } = useVoiceRamble({
    getInput: () => inputRef.current?.value ?? prompt,
    onError: setError,
    onTranscript: (text, wasEmptyAtStart) => {
      const combined = appendTranscript(inputRef.current?.value ?? prompt, text);
      setPrompt(combined);
      if (wasEmptyAtStart) void submit(undefined, combined);
      else setTimeout(() => inputRef.current?.focus(), 0);
    },
  });

  // Refill the input when a past prompt is reused from the history panel.
  useEffect(() => {
    if (seed) {
      setPrompt(seed);
      setTimeout(() => inputRef.current?.focus(), 0);
      onSeedConsumed?.();
    }
  }, [seed, onSeedConsumed]);

  // Focus the bar on demand (creation-bar shortcut / command).
  useEffect(() => {
    if (focusSignal) inputRef.current?.focus();
  }, [focusSignal]);

  const clearClarification = () => {
    setExchange(null);
    setPrompt("");
  };

  // Send the exchange so far, with `answerText` filling in the LAST (pending)
  // turn — every earlier answer is preserved (the R-102 answer-drop fix).
  // `exchange` must be non-null when this is called. `buildNow` (the "Just build
  // it" skip) sends build_now:true so the backend hard-caps and never returns
  // another question — the skip is a HARD build by construction.
  const resolveExchange = async (answerText: string, buildNow = false) => {
    const { original, turns } = exchange as Exchange;
    const turnsToSend = [
      ...turns.slice(0, -1),
      { ...turns[turns.length - 1], answer: answerText },
    ];
    const result = await api.previewModules(original, activePageId, turnsToSend, buildNow);
    if (result.question) {
      // Another question — push a new turn (route caps this at 4 answered).
      setExchange({ original, turns: [...turnsToSend, { question: result.question, answer: "" }] });
      setPrompt("");
      setTimeout(() => inputRef.current?.focus(), 0);
    } else if (result.previews?.length) {
      setPreviews(result.previews);
      setPlan(result.plan ?? null);
      lastPromptRef.current = original;
      setPrompt("");
      setExchange(null);
    }
    if (result.degraded) setError(DEGRADED_NOTICE);
  };

  // The default "fresh proposal" path: previewModules with no interfering
  // state. Extracted so a typed Enter (the default submit branch) and the R-105
  // entry handoff (submit(..., fresh=true)) open a brand-new proposal identically.
  const runFreshPreview = async (v: string) => {
    const result = await api.previewModules(v, activePageId);
    if (result.question) {
      // AI needs clarification — enter follow-up mode.
      setExchange({ original: v, turns: [{ question: result.question, answer: "" }] });
      setPrompt("");
      setTimeout(() => inputRef.current?.focus(), 0);
    } else if (result.previews?.length) {
      // Show a preview stack to accept before anything lands on the canvas.
      lastPromptRef.current = v;
      setPreviews(result.previews);
      setPlan(result.plan ?? null);
      setPrompt("");
    }
    if (result.degraded) setError(DEGRADED_NOTICE);
  };

  // `overrideText` lets a voice auto-submit (R-202) drive this with the
  // just-appended transcript without waiting a render for `prompt` state to
  // catch up — every non-fresh branch still reads current component state
  // (isRefining/file/exchange/previews), so the auto-submit takes whichever
  // path a typed Enter would take right now (default preview, refine-the-
  // preview, or resolving a pending interview question). `fresh=true` (the R-105
  // entry handoff) bypasses all of that and forces a brand-new proposal.
  const submit = async (e?: React.FormEvent, overrideText?: string, fresh = false) => {
    e?.preventDefault();
    const v = (overrideText ?? prompt).trim();
    if ((!v && !file) || loading) return;
    setLoading(true);
    setError(null);
    try {
      if (fresh) {
        // R-105: the entry-screen handoff must ALWAYS open a brand-new proposal,
        // even over a dirty PromptBar (preview stack / pending question / attached
        // file / refine target) — otherwise the fresh prompt gets folded into a
        // refine-join or sent as the answer to a stale question. Clear the
        // interfering state first, then run the default preview path.
        setPreviews([]);
        setPlan(null);
        setExchange(null);
        setFile(null);
        onClearRefine?.();
        await runFreshPreview(v);
      } else if (previews.length > 0 && !isRefining && !file) {
        // Talk to the preview: refine the proposed tools before adding them.
        const combined = `${lastPromptRef.current} — ${v}`;
        const result = await api.previewModules(combined, activePageId);
        if (result.question) {
          setExchange({ original: combined, turns: [{ question: result.question, answer: "" }] });
        } else if (result.previews?.length) {
          setPreviews(result.previews);
          setPlan(result.plan ?? null);
          lastPromptRef.current = combined;
        }
        if (result.degraded) setError(DEGRADED_NOTICE);
        setPrompt("");
      } else if (isRefining && refineTarget && onRefineModule) {
        const updated = await api.refineModule(refineTarget.id, v);
        onRefineModule(updated);
        setPrompt("");
      } else if (file) {
        // R-223 backlog: preview-then-confirm for a file attach, mirroring the
        // text-generation preview stack — the tools no longer land on the
        // canvas straight away.
        const result = await api.generateModuleFromFile(file, v, activePageId, undefined, true);
        if (result.previews?.length) {
          lastPromptRef.current = v || file.name;
          setPreviews(result.previews);
          setPlan(result.plan ?? null);
        }
        if (result.degraded) setError(DEGRADED_NOTICE);
        setPrompt("");
        setFile(null);
        clearClarification();
      } else if (exchange) {
        // Answering a pending question in an ongoing interview.
        await resolveExchange(v);
      } else {
        await runFreshPreview(v);
      }
    } catch (err) {
      // Deliberate: a failed request mid-interview RETAINS the exchange state so
      // the user can retry their answer without losing the whole Q/A chain.
      if (err instanceof ApiError && err.refusal) {
        setError(err.refusal);
      } else if (err instanceof ApiError && err.question) {
        // R-304: refine asked a clarifying question — show its text, not raw JSON.
        setError(err.question);
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Something went wrong.");
      }
    } finally {
      setLoading(false);
    }
  };

  // R-102 skip: answer the pending question with a canned "use your best
  // judgment" so the interview ends immediately, at any step.
  const skipToBuild = async () => {
    if (!exchange || loading) return;
    setLoading(true);
    setError(null);
    try {
      await resolveExchange(SKIP_ANSWER, true); // build_now → a HARD build, never re-questioned
    } catch (err) {
      if (err instanceof ApiError && err.refusal) setError(err.refusal);
      else if (err instanceof ApiError && err.question) setError(err.question);
      else if (err instanceof Error) setError(err.message);
      else setError("Something went wrong.");
    } finally {
      setLoading(false);
    }
  };

  // R-101/R-105: a prompt handed over from the entry-screen front door. Fill it
  // in and auto-submit ONCE with fresh=true, which clears any in-flight preview/
  // interview/refine/file state first so re-entry over a dirty PromptBar still
  // produces a brand-new proposal (not a refine-join or a stale-question answer).
  // Cleared immediately via onAutoPromptConsumed so it can never re-fire.
  useEffect(() => {
    const v = autoPrompt?.trim();
    if (!v) return;
    setPrompt(autoPrompt as string);
    void submit(undefined, v, true);
    onAutoPromptConsumed?.();
  // submit closes over current state; we intentionally run only on autoPrompt change.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoPrompt]);

  const addConfigs = async (configs: ModuleConfig[]) => {
    try {
      const stored = await api.insertModules(configs, lastPromptRef.current, activePageId);
      stored.forEach((m) => onModule(m));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't add to canvas.");
    }
  };
  const addAll = async () => { await addConfigs(previews); setPreviews([]); setPlan(null); };
  const addOne = async (i: number) => { await addConfigs([previews[i]]); setPreviews((p) => p.filter((_, idx) => idx !== i)); };
  const dismissOne = (i: number) => setPreviews((p) => p.filter((_, idx) => idx !== i));
  const dismissAll = () => { setPreviews([]); setPlan(null); };
  // Inline edits to a preview (typing into its fields) flow back into the config.
  const updatePreview = (i: number, m: StoredModule) => setPreviews((p) => p.map((c, idx) => (idx === i ? m.config : c)));

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      if (pendingQuestion) clearClarification();
      else if (isRefining) onClearRefine?.();
    }
  };

  const previewing = previews.length > 0 && !isRefining && !file;
  const placeholder = pendingQuestion
    ? `${pendingQuestion}`
    : previewing
      ? "Adjust these — e.g. make the budget a chart, add a notes field"
      : isRefining
        ? "Describe what to change — e.g. add a rest day checkbox"
        : "Describe what you want to organize — e.g. track my workouts";

  const buttonLabel = loading
    ? (isRefining ? "Refining…" : file ? "Building…" : previewing ? "Refining…" : "Generating…")
    : previewing
      ? "Refine"
      : isRefining
        ? "Refine"
        : file
          ? "Build"
          : pendingQuestion
            ? "Answer"
            : "Generate";

  return (
    <form
      onSubmit={submit}
      className="absolute left-1/2 -translate-x-1/2 bottom-6 w-[min(720px,calc(100%-2rem))] z-10"
    >
      <div className="flex flex-col rounded-2xl border border-[var(--border)] bg-[var(--surface)]/95 backdrop-blur shadow-2xl shadow-black/40 overflow-hidden">

        {previews.length > 0 && (
          <div className="flex flex-col gap-3 px-3 pt-3 pb-1 max-h-[60vh] overflow-y-auto">
            {/* R-103/R-301: the plan is a muted single paragraph — no new visual
                language, same treatment as the other secondary/hint text below. */}
            {plan && (
              <p className="px-1 text-xs text-[var(--muted)] leading-relaxed">{plan}</p>
            )}
            <div className="flex items-center gap-2 px-1">
              <span className="text-[10px] uppercase tracking-wide text-[var(--muted)] font-mono">
                {previews.length} tool{previews.length === 1 ? "" : "s"} proposed — preview &amp; edit
              </span>
              <button type="button" onClick={addAll}
                className="ml-auto rounded-md bg-[var(--accent)] text-[var(--accent-fg)] px-2.5 py-1 text-xs font-medium hover:brightness-110 transition">
                Add all to canvas
              </button>
              <button type="button" onClick={dismissAll}
                className="text-xs text-[var(--muted)] hover:text-[var(--foreground)] transition">Dismiss</button>
            </div>
            {previews.map((cfg, i) => (
              <div key={i} className="animate-pop">
                <Module
                  variant="preview"
                  module={{ id: `preview-${i}`, config: cfg, created_at: NOW, updated_at: NOW, archived: false, rev: 0 }}
                  crossModuleValues={{}}
                  selected={false}
                  onChange={(m) => updatePreview(i, m)}
                  onArchive={noop} onUndo={noop} onSelectForRefine={noop} onSelect={noop}
                  onDragStart={noop} onResizeStart={noop}
                />
                <div className="flex items-center gap-2 mt-1 px-1">
                  <span className="text-[10px] text-[var(--muted)]">Edit fields inline, then</span>
                  <button type="button" onClick={() => addOne(i)}
                    className="ml-auto rounded-md border border-[var(--accent)] text-[var(--accent)] px-2.5 py-0.5 text-xs hover:bg-[var(--accent)] hover:text-[var(--accent-fg)] transition">Add to canvas</button>
                  <button type="button" onClick={() => dismissOne(i)}
                    className="text-[var(--muted)] hover:text-[var(--danger)] text-xs" aria-label="Dismiss">Dismiss</button>
                </div>
              </div>
            ))}
          </div>
        )}

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

        {pendingQuestion && !isRefining && (
          <div className="flex items-start gap-2 px-4 pt-2.5 pb-0">
            <span className="text-[10px] uppercase tracking-wide text-[var(--muted)] font-mono shrink-0 mt-0.5">
              Question {questionNumber} of 4
            </span>
            <span className="text-xs text-[var(--foreground)] flex-1">
              {pendingQuestion}
            </span>
            <button
              type="button"
              onClick={skipToBuild}
              disabled={loading}
              className="text-[var(--accent)] hover:brightness-110 transition text-xs shrink-0 disabled:opacity-40"
            >
              Just build it
            </button>
            <button
              type="button"
              onClick={clearClarification}
              className="text-[var(--muted)] hover:text-[var(--foreground)] transition text-xs shrink-0"
              aria-label="Cancel"
            >
              ✕ cancel
            </button>
          </div>
        )}

        {file && (
          <div className="flex items-center gap-2 px-4 pt-2.5 pb-0">
            <span className="text-[10px] uppercase tracking-wide text-[var(--muted)] font-mono">Attached</span>
            <span className="text-xs text-[var(--accent)] truncate max-w-[260px] flex items-center gap-1"><Icon name="paperclip" size={12} /> {file.name}</span>
            <button type="button" onClick={() => setFile(null)} className="ml-auto text-[var(--muted)] hover:text-[var(--foreground)] transition text-xs shrink-0" aria-label="Remove file">✕ remove</button>
          </div>
        )}

        {(recording || transcribing) && (
          <div className="flex items-center gap-2 px-4 pt-2.5 pb-0">
            <span
              className={`text-[10px] uppercase tracking-wide font-mono shrink-0 animate-pulse ${
                recording ? "text-[var(--danger)]" : "text-[var(--accent)]"
              }`}
            >
              {recording ? `Recording ${formatElapsed(elapsedSec)}` : "Transcribing…"}
            </span>
            {recording && liveInterim && (
              <span className="text-xs text-[var(--muted)] italic opacity-70 truncate flex-1" aria-hidden>
                {liveInterim}
              </span>
            )}
          </div>
        )}

        <div className="flex items-center gap-2 px-4 py-3">
          {voiceMode !== "none" && (
            <button
              type="button"
              onClick={toggleMic}
              disabled={transcribing}
              className={`shrink-0 w-8 h-8 grid place-items-center rounded-full transition disabled:opacity-40 ${
                recording ? "bg-[var(--danger)] text-white animate-pulse" : "text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--surface-elevated)]"
              }`}
              title={recording ? "Stop recording" : transcribing ? "Transcribing…" : "Speak"}
              aria-label={recording ? "Stop recording" : transcribing ? "Transcribing" : "Voice input"}
            >
              <Icon name="mic" size={16} />
            </button>
          )}
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className="shrink-0 w-8 h-8 grid place-items-center rounded-full text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--surface-elevated)] transition"
            title="Attach a document or image"
            aria-label="Attach file"
          >
            <Icon name="paperclip" size={16} />
          </button>
          <input
            ref={fileRef}
            type="file"
            className="hidden"
            accept="image/*,application/pdf,.csv,.txt,.md"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) setFile(f); e.target.value = ""; }}
          />
          <input
            ref={inputRef}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={loading}
            placeholder={placeholder}
            className="flex-1 bg-transparent text-sm placeholder:text-[var(--muted)] focus:outline-none disabled:opacity-50"
            autoFocus
          />
          <button
            type="submit"
            disabled={(!prompt.trim() && !file) || loading}
            className={`rounded-md bg-[var(--accent)] text-[var(--accent-fg)] px-3 py-1.5 text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:brightness-110 active:scale-95 transition shrink-0 ${loading ? "animate-pulse" : ""}`}
          >
            {buttonLabel}
          </button>
        </div>

        {error && (
          <div className="px-4 pb-3 -mt-1">
            {/* R-1305: the degraded/offline-fallback notice is informational, not
                a failure — it carries the save-pill's neutral "warning" treatment
                (muted text, a small static marker), never the terracotta --danger
                error channel that real refusals/errors use. */}
            {error === DEGRADED_NOTICE ? (
              <div className="flex items-center gap-1.5 text-xs text-[var(--muted)]">
                <span aria-hidden className="w-1.5 h-1.5 rounded-full bg-[var(--muted)]" />
                <span>{error}</span>
              </div>
            ) : (
              <div className="text-xs text-[var(--danger)]">{error}</div>
            )}
          </div>
        )}
      </div>
    </form>
  );
}
