"use client";

import type { ReactNode } from "react";
import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { Icon } from "@/components/Icon";

// R-901/R-902: claiming is a two-step, explicit gesture — preview the invite
// (read-only GET, mutates nothing) then require a click before the POST that
// actually claims it. A GET must never silently adopt a browser's anonymous
// work or hijack a session (see `backend/src/routes/auth.py`).
type Phase = "loading" | "error" | "preview" | "claiming" | "rebind" | "switching";

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 404) return "This invite link isn't valid — it doesn't match an active invite.";
    if (err.status === 403) return "This invite has been revoked.";
    return err.message || fallback;
  }
  return fallback;
}

function Shell({ children }: { children: ReactNode }) {
  return (
    <main className="fixed inset-0 grid place-items-center bg-[var(--background)]">
      <div className="canvas-grid absolute inset-0 opacity-40" aria-hidden />
      <div className="relative text-center px-6 max-w-md">
        <div className="flex items-center justify-center gap-2 text-[var(--accent)] mb-6 animate-rise">
          <Icon name="sparkles" size={22} />
          <span className="text-lg font-semibold tracking-tight text-[var(--foreground)]">Trus</span>
        </div>
        {children}
      </div>
    </main>
  );
}

function ClaimInner() {
  const params = useSearchParams();
  const router = useRouter();
  const token = params.get("token");
  const [phase, setPhase] = useState<Phase>("loading");
  const [previewName, setPreviewName] = useState<string | null>(null);
  const [currentName, setCurrentName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      setError("This invite link is missing its token.");
      setPhase("error");
      return;
    }
    api
      .authClaimPreview(token)
      .then((r) => {
        setPreviewName(r.name);
        setPhase("preview");
      })
      .catch((err) => {
        setError(errorMessage(err, "This invite could not be verified."));
        setPhase("error");
      });
  }, [token]);

  const claim = useCallback(
    (confirm: boolean) => {
      if (!token) return;
      setPhase(confirm ? "switching" : "claiming");
      api
        .authClaim(token, confirm)
        .then(() => router.replace("/"))
        .catch((err) => {
          if (err instanceof ApiError && err.status === 409 && err.rebind) {
            setCurrentName(err.rebind);
            setPhase("rebind");
            return;
          }
          setError(errorMessage(err, "This invite could not be claimed."));
          setPhase("error");
        });
    },
    [token, router],
  );

  if (phase === "loading") {
    return (
      <Shell>
        <p className="text-sm text-[var(--muted)] animate-rise" style={{ animationDelay: "0.05s" }}>
          Checking your invite…
        </p>
      </Shell>
    );
  }

  if (phase === "error") {
    return (
      <Shell>
        <h1 className="text-2xl font-semibold tracking-tight animate-rise" style={{ animationDelay: "0.05s" }}>
          Couldn&apos;t open this invite
        </h1>
        <p
          className="mt-4 text-sm text-[var(--muted)] leading-relaxed animate-rise"
          style={{ animationDelay: "0.15s" }}
        >
          {error}
        </p>
      </Shell>
    );
  }

  if (phase === "rebind") {
    return (
      <Shell>
        <h1 className="text-2xl font-semibold tracking-tight animate-rise" style={{ animationDelay: "0.05s" }}>
          Switch workspace?
        </h1>
        <p
          className="mt-4 text-sm text-[var(--muted)] leading-relaxed animate-rise"
          style={{ animationDelay: "0.15s" }}
        >
          This browser is signed in as{" "}
          <span className="text-[var(--foreground)]">{currentName}</span>. Switch to{" "}
          <span className="text-[var(--foreground)]">{previewName}</span>? Your existing work
          stays with {currentName}.
        </p>
        <button
          type="button"
          onClick={() => claim(true)}
          className="press mt-6 rounded-md bg-[var(--accent)] text-[var(--accent-fg)] px-4 py-2 text-sm font-medium hover:brightness-110 transition animate-rise"
          style={{ animationDelay: "0.25s" }}
        >
          Switch to {previewName}
        </button>
      </Shell>
    );
  }

  if (phase === "switching") {
    return (
      <Shell>
        <p className="text-sm text-[var(--muted)] animate-rise">Switching workspace…</p>
      </Shell>
    );
  }

  if (phase === "claiming") {
    return (
      <Shell>
        <p className="text-sm text-[var(--muted)] animate-rise">Claiming your workspace…</p>
      </Shell>
    );
  }

  // phase === "preview"
  return (
    <Shell>
      <h1 className="text-2xl font-semibold tracking-tight animate-rise" style={{ animationDelay: "0.05s" }}>
        Claim this workspace as {previewName}?
      </h1>
      <p
        className="mt-4 text-sm text-[var(--muted)] leading-relaxed animate-rise"
        style={{ animationDelay: "0.15s" }}
      >
        This link enters your workspace on this device.
      </p>
      <button
        type="button"
        onClick={() => claim(false)}
        className="press mt-6 rounded-md bg-[var(--accent)] text-[var(--accent-fg)] px-4 py-2 text-sm font-medium hover:brightness-110 transition animate-rise"
        style={{ animationDelay: "0.25s" }}
      >
        Claim workspace
      </button>
    </Shell>
  );
}

export default function ClaimPage() {
  return (
    <Suspense fallback={null}>
      <ClaimInner />
    </Suspense>
  );
}
