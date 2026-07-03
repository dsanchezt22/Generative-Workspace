"use client";

// R-101/R-105: the entry-as-interview front door. A TRUE pre-workspace surface
// (not a decorative splash) that accepts input directly: a rotating prompt
// headline, a large mic as the visually PRIMARY control, and a text field as the
// visible secondary. Either input goes through the normal preview/interview flow
// (handed to PromptBar via onSubmit), then this dissolves to the canvas.
//
// Reuses the old IntroSplash anatomy/tokens — sparkles + wordmark, canvas-grid
// texture, rise/fade motion, the typewriter rotator (now cycling full prompt
// phrases, "Tell me what's on your mind" first — the spec's canonical copy).
//
// A11y (R-1306 floor): role="dialog" aria-modal, focus starts on the text field,
// Escape and a visible keyboard-reachable "Skip" dismiss to the canvas.

import { useEffect, useRef, useState } from "react";
import { appendTranscript, formatElapsed } from "@/lib/voiceRamble";
import { useVoiceRamble } from "@/lib/useVoiceRamble";
import { nextTypewriterState, type TypewriterState } from "@/lib/typewriter";
import { Icon } from "./Icon";

const HEADLINES = [
  "Tell me what's on your mind", // R-101 canonical copy — always first
  "What do you want to organize?",
  "Describe a tool — watch it build",
  "Plan a trip. Track a habit. Budget a month.",
];

interface Props {
  // Hand the collected prompt to the normal preview/interview flow (PromptBar).
  onSubmit: (prompt: string) => void;
  // Dismiss to the canvas without submitting (Skip / Escape).
  onSkip: () => void;
}

export function EntryScreen({ onSubmit, onSkip }: Props) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  // Plays the dissolve-out before handing off, so the canvas is revealed with
  // the existing rise/fade motion rather than a hard cut.
  const [leaving, setLeaving] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // Rotating headline typewriter (shared pure step fn — see lib/typewriter).
  const [tw, setTw] = useState<TypewriterState>({ text: "", phraseIndex: 0, deleting: false });
  useEffect(() => {
    const { state, delayMs } = nextTypewriterState(tw, HEADLINES);
    const t = window.setTimeout(() => setTw(state), delayMs);
    return () => window.clearTimeout(t);
  }, [tw]);

  // Focus the text field on mount (R-1306: focus starts on the field).
  useEffect(() => {
    const t = window.setTimeout(() => inputRef.current?.focus(), 60);
    return () => window.clearTimeout(t);
  }, []);

  // Dissolve, then run the handoff/dismiss. Under reduced motion the CSS crushes
  // the opacity transition to ~0, so the wait must match — dismiss instantly
  // rather than sitting on a blank screen for 260ms (same signal the app uses:
  // the data-motion override, then the OS setting).
  const leave = (action: () => void) => {
    if (leaving) return;
    setLeaving(true);
    const motion = typeof document !== "undefined" ? document.documentElement.dataset.motion : undefined;
    const reduce =
      motion === "reduced" ||
      (motion !== "full" && typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
    window.setTimeout(action, reduce ? 0 : 260);
  };

  const submitPrompt = (value: string) => {
    const v = value.trim();
    if (!v) return;
    leave(() => onSubmit(v));
  };

  const { voiceMode, recording, transcribing, elapsedSec, liveInterim, toggleMic } = useVoiceRamble({
    getInput: () => inputRef.current?.value ?? text,
    onError: setError,
    onTranscript: (transcript, wasEmptyAtStart) => {
      const combined = appendTranscript(inputRef.current?.value ?? text, transcript);
      setText(combined);
      // R-202: an empty field at record-start means "speak and go" — submit
      // straight to the preview flow; otherwise leave it for the user to edit.
      if (wasEmptyAtStart) submitPrompt(combined);
      else setTimeout(() => inputRef.current?.focus(), 0);
    },
  });

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { e.preventDefault(); leave(onSkip); }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Start with a conversation"
      onKeyDown={handleKeyDown}
      className={`fixed inset-0 z-[60] grid place-items-center bg-[var(--background)] animate-fade transition-opacity duration-300 ${leaving ? "opacity-0" : ""}`}
    >
      <div className="canvas-grid absolute inset-0 opacity-40" aria-hidden />

      <div className="relative w-full max-w-2xl px-6 text-center">
        {/* Brand stamp */}
        <div className="flex items-center justify-center gap-2 text-[var(--accent)] mb-8 animate-rise">
          <Icon name="sparkles" size={22} />
          <span className="text-lg font-semibold tracking-tight text-[var(--foreground)]">Trus</span>
        </div>

        {/* Rotating prompt headline — the typewriter constructs itself (ethos:
            generated, not drawn). A stable phrase is exposed to SRs. */}
        <h1
          className="text-3xl sm:text-5xl font-semibold tracking-tight animate-rise min-h-[2.6rem] sm:min-h-[3.6rem]"
          style={{ animationDelay: "0.05s" }}
        >
          <span aria-hidden>
            {tw.text || " "}
            <span className="blink text-[var(--accent)] ml-0.5">|</span>
          </span>
          <span className="sr-only">{HEADLINES[0]}</span>
        </h1>

        {/* PRIMARY control: the mic. The one magenta spark on this screen
            (DESIGN-ETHOS §1.2). Hidden entirely when no capture API exists. */}
        {voiceMode !== "none" && (
          <div className="mt-10 flex flex-col items-center animate-rise" style={{ animationDelay: "0.15s" }}>
            <button
              type="button"
              onClick={toggleMic}
              disabled={transcribing}
              className={`relative grid place-items-center w-24 h-24 rounded-full transition disabled:opacity-60 disabled:cursor-not-allowed active:scale-95 ${
                recording
                  ? "bg-[var(--danger)] text-white animate-pulse shadow-2xl shadow-black/40"
                  : "bg-[var(--accent)] text-[var(--accent-fg)] hover:brightness-110 shadow-2xl shadow-black/40"
              }`}
              style={recording || transcribing ? undefined : { boxShadow: "var(--accent-blue-glow), 0 20px 60px rgba(0,0,0,0.4)" }}
              aria-label={recording ? "Stop recording" : transcribing ? "Transcribing" : "Speak — tell me what's on your mind"}
              title={recording ? "Stop recording" : transcribing ? "Transcribing…" : "Speak"}
            >
              <Icon name="mic" size={34} />
            </button>
            <div className="mt-4 h-5 text-xs" aria-live="polite">
              {recording ? (
                <span className="font-mono tracking-wide text-[var(--danger)] animate-pulse">
                  Recording {formatElapsed(elapsedSec)} — tap to stop
                </span>
              ) : transcribing ? (
                <span className="font-mono tracking-wide text-[var(--accent)] animate-pulse">Transcribing…</span>
              ) : (
                <span className="text-[var(--muted)]">Tap and talk — I&apos;ll build from what you say</span>
              )}
            </div>
            {recording && liveInterim && (
              <p className="mt-1 max-w-md text-sm text-[var(--muted)] italic opacity-70 line-clamp-2" aria-hidden>
                {liveInterim}
              </p>
            )}
          </div>
        )}

        {/* SECONDARY input: type it instead. Matte, never the magenta spark. */}
        <form
          onSubmit={(e) => { e.preventDefault(); submitPrompt(text); }}
          className="mt-8 mx-auto flex items-center gap-2 w-full max-w-lg rounded-xl border border-[var(--border)] bg-[var(--surface)]/90 backdrop-blur px-3.5 py-2.5 focus-within:border-[var(--accent)] transition-colors animate-rise"
          style={{ animationDelay: "0.22s" }}
        >
          <input
            ref={inputRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="…or type what you want to organize"
            className="flex-1 bg-transparent text-sm placeholder:text-[var(--muted)] focus:outline-none"
          />
          <button
            type="submit"
            disabled={!text.trim()}
            className="shrink-0 grid place-items-center w-8 h-8 rounded-lg border border-[var(--border)] text-[var(--muted)] hover:text-[var(--foreground)] hover:border-[var(--foreground)] disabled:opacity-40 disabled:cursor-not-allowed transition"
            aria-label="Start"
            title="Start"
          >
            <Icon name="chevronRight" size={18} />
          </button>
        </form>

        {error && <p className="mt-3 text-xs text-[var(--danger)]">{error}</p>}

        {/* Keyboard-reachable dismiss (R-1306). Quiet, matte — not an action. */}
        <button
          type="button"
          onClick={() => leave(onSkip)}
          className="mt-10 text-xs text-[var(--muted)] hover:text-[var(--foreground)] transition animate-rise"
          style={{ animationDelay: "0.3s" }}
        >
          Skip — go straight to the canvas
        </button>
      </div>
    </div>
  );
}
