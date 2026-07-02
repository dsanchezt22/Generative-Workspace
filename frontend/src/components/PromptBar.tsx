"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { ModuleConfig, StoredModule } from "@/lib/types";
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
}

export function PromptBar({ onModule, activePageId, refineTarget, onRefineModule, onClearRefine, seed, onSeedConsumed, focusSignal }: Props) {
  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Clarifying question state: when the AI needs one more answer before generating.
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const originalPromptRef = useRef<string>("");
  const inputRef = useRef<HTMLInputElement | null>(null);

  const isRefining = Boolean(refineTarget);
  const [recording, setRecording] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [previews, setPreviews] = useState<ModuleConfig[]>([]);
  const lastPromptRef = useRef<string>("");
  const fileRef = useRef<HTMLInputElement | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recRef = useRef<any>(null);

  const toggleMic = () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) { setError("Voice input isn't supported in this browser."); return; }
    if (recording) { recRef.current?.stop(); return; }
    const rec = new SR();
    rec.lang = "en-US";
    rec.interimResults = true;
    rec.continuous = false;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    rec.onresult = (e: any) => {
      let t = "";
      for (let i = 0; i < e.results.length; i++) t += e.results[i][0].transcript;
      setPrompt(t);
    };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    rec.onerror = (e: any) => {
      setError(e.error === "not-allowed" ? "Microphone blocked — allow access to use voice." : "Didn't catch that — try again.");
      setRecording(false);
    };
    rec.onend = () => setRecording(false);
    recRef.current = rec;
    rec.start();
    setRecording(true);
    setError(null);
  };

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
    setPendingQuestion(null);
    originalPromptRef.current = "";
    setPrompt("");
  };

  const submit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const v = prompt.trim();
    if ((!v && !file) || loading) return;
    setLoading(true);
    setError(null);
    try {
      if (previews.length > 0 && !isRefining && !file) {
        // Talk to the preview: refine the proposed tools before adding them.
        const combined = `${lastPromptRef.current} — ${v}`;
        const result = await api.previewModules(combined, activePageId);
        if (result.question) setPendingQuestion(result.question);
        else if (result.previews?.length) { setPreviews(result.previews); lastPromptRef.current = combined; }
        if (result.degraded) setError(DEGRADED_NOTICE);
        setPrompt("");
      } else if (isRefining && refineTarget && onRefineModule) {
        const updated = await api.refineModule(refineTarget.id, v);
        onRefineModule(updated);
        setPrompt("");
      } else if (file) {
        const result = await api.generateModuleFromFile(file, v, activePageId);
        if (result.modules?.length) result.modules.forEach((m) => onModule(m));
        else if (result.module) onModule(result.module);
        if (result.degraded) setError(DEGRADED_NOTICE);
        setPrompt("");
        setFile(null);
        clearClarification();
      } else {
        // If we're answering a clarifying question, combine original + answer.
        const fullPrompt = pendingQuestion
          ? `${originalPromptRef.current} — ${v}`
          : v;
        const result = await api.previewModules(fullPrompt, activePageId);
        if (result.question) {
          // AI needs clarification — enter follow-up mode.
          if (!pendingQuestion) originalPromptRef.current = v;
          setPendingQuestion(result.question);
          setPrompt("");
          setTimeout(() => inputRef.current?.focus(), 0);
        } else if (result.previews?.length) {
          // Show a preview stack to accept before anything lands on the canvas.
          lastPromptRef.current = fullPrompt;
          setPreviews(result.previews);
          setPrompt("");
          setPendingQuestion(null);
          originalPromptRef.current = "";
        }
        if (result.degraded) setError(DEGRADED_NOTICE);
      }
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

  const addConfigs = async (configs: ModuleConfig[]) => {
    try {
      const stored = await api.insertModules(configs, lastPromptRef.current, activePageId);
      stored.forEach((m) => onModule(m));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't add to canvas.");
    }
  };
  const addAll = async () => { await addConfigs(previews); setPreviews([]); };
  const addOne = async (i: number) => { await addConfigs([previews[i]]); setPreviews((p) => p.filter((_, idx) => idx !== i)); };
  const dismissOne = (i: number) => setPreviews((p) => p.filter((_, idx) => idx !== i));
  const dismissAll = () => setPreviews([]);
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
                  module={{ id: `preview-${i}`, config: cfg, created_at: NOW, updated_at: NOW }}
                  crossModuleValues={{}}
                  selected={false}
                  onChange={(m) => updatePreview(i, m)}
                  onDelete={noop} onUndo={noop} onSelectForRefine={noop} onSelect={noop}
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
              One question
            </span>
            <span className="text-xs text-[var(--foreground)] flex-1">
              {pendingQuestion}
            </span>
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

        <div className="flex items-center gap-2 px-4 py-3">
          <button
            type="button"
            onClick={toggleMic}
            className={`shrink-0 w-8 h-8 grid place-items-center rounded-full transition ${
              recording ? "bg-[var(--danger)] text-white animate-pulse" : "text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--surface-elevated)]"
            }`}
            title={recording ? "Stop recording" : "Speak"}
            aria-label={recording ? "Stop recording" : "Voice input"}
          >
            <Icon name="mic" size={16} />
          </button>
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
            <div className="text-xs text-[var(--danger)]">{error}</div>
          </div>
        )}
      </div>
    </form>
  );
}
