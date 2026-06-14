"use client";

import { useEffect, useState } from "react";
import { Icon } from "./Icon";

const PHRASES = [
  "a trip to Japan",
  "tax-filing documents",
  "my flower shop's income",
  "marathon training",
  "this semester's classes",
  "the household budget",
  "a wedding guest list",
  "my reading list",
];

export function IntroSplash({ onDone }: { onDone: () => void }) {
  const [text, setText] = useState("");
  const [pi, setPi] = useState(0);
  const [deleting, setDeleting] = useState(false);

  // Typewriter: type a phrase, hold, delete, advance to the next.
  useEffect(() => {
    const full = PHRASES[pi % PHRASES.length];
    let t: number;
    if (!deleting) {
      if (text.length < full.length) t = window.setTimeout(() => setText(full.slice(0, text.length + 1)), 55);
      else t = window.setTimeout(() => setDeleting(true), 1200);
    } else {
      if (text.length > 0) t = window.setTimeout(() => setText(full.slice(0, text.length - 1)), 28);
      else { setDeleting(false); setPi((p) => p + 1); return; }
    }
    return () => window.clearTimeout(t);
  }, [text, deleting, pi]);

  // Auto-dismiss, and allow click / any key to skip.
  useEffect(() => {
    const t = window.setTimeout(onDone, 8000);
    const onKey = () => onDone();
    window.addEventListener("keydown", onKey);
    return () => { window.clearTimeout(t); window.removeEventListener("keydown", onKey); };
  }, [onDone]);

  return (
    <div
      className="fixed inset-0 z-[60] grid place-items-center bg-[var(--background)] cursor-pointer animate-fade"
      onClick={onDone}
    >
      <div className="canvas-grid absolute inset-0 opacity-40" aria-hidden />
      <div className="relative text-center px-6 max-w-2xl">
        <div className="flex items-center justify-center gap-2 text-[var(--accent)] mb-6 animate-rise">
          <Icon name="sparkles" size={22} />
          <span className="text-lg font-semibold tracking-tight text-[var(--foreground)]">Trus</span>
        </div>
        <h1 className="text-3xl sm:text-5xl font-semibold tracking-tight animate-rise" style={{ animationDelay: "0.05s" }}>
          What&apos;s on your mind?
        </h1>
        <p className="mt-6 text-xl sm:text-2xl text-[var(--muted)] animate-rise" style={{ animationDelay: "0.15s" }}>
          Organize{" "}
          <span className="text-[var(--foreground)] font-medium border-b-2 border-[var(--accent)] pb-0.5">
            {text || " "}
          </span>
          <span className="blink text-[var(--accent)] ml-0.5">|</span>
        </p>
        <p className="mt-10 text-xs text-[var(--muted)] animate-rise" style={{ animationDelay: "0.3s" }}>
          click anywhere to begin
        </p>
      </div>
    </div>
  );
}
