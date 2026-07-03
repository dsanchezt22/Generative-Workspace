"use client";

import { Icon } from "./Icon";

// R-901: shown instead of the canvas when a session has no live, claimed
// invite and anonymous access is off (TRUS_ALLOW_ANON=0). No inputs — the
// only way in is an invite link (see `/claim`).
export function InviteGate() {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-[var(--background)]">
      <div className="canvas-grid absolute inset-0 opacity-40" aria-hidden />
      <div className="relative text-center px-6 max-w-md">
        <div className="flex items-center justify-center gap-2 text-[var(--accent)] mb-6 animate-rise">
          <Icon name="sparkles" size={22} />
          <span className="text-lg font-semibold tracking-tight text-[var(--foreground)]">Trus</span>
        </div>
        <h1
          className="text-2xl sm:text-3xl font-semibold tracking-tight animate-rise"
          style={{ animationDelay: "0.05s" }}
        >
          Trus is invite-only right now
        </h1>
        <p
          className="mt-4 text-sm text-[var(--muted)] leading-relaxed animate-rise"
          style={{ animationDelay: "0.15s" }}
        >
          Open your invite link on this device to enter your workspace.
        </p>
      </div>
    </div>
  );
}
