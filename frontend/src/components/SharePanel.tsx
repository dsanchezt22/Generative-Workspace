"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { ShareStatus } from "@/lib/types";
import { useDialog } from "@/lib/useDialog";
import { ConfirmDialog } from "./ConfirmDialog";
import { Icon } from "./Icon";

// Pure (no Date.now()): a saved ISO instant formats deterministically.
function formatCreated(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

interface Props {
  pageId: string;
  onClose: () => void;
  // Lifts the active/inactive state to Home so the header pip stays in sync
  // without a re-fetch.
  onStateChange: (active: boolean) => void;
}

// DESIGN-sharing §4e — the share affordance. Modeled on SnapshotsPanel: a
// right-side dialog aside via useDialog. On open it FETCHES the current status
// (it never POSTs just to display a link). The ConfirmDialog is a SIBLING of the
// aside, never nested: animate-slide-right makes the aside a transform containing
// block, which would otherwise trap the dialog's fixed positioning (2a-3 lesson).
export function SharePanel({ pageId, onClose, onStateChange }: Props) {
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const { ref: dialogRef, onKeyDown } = useDialog<HTMLElement>(true, onClose, closeRef);
  const [status, setStatus] = useState<ShareStatus | null>(null); // null = still resolving
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<null | "rotate" | "revoke">(null);
  const [copied, setCopied] = useState(false);
  // AUT×SHARE disclosure: does an agent write to this page? If so, sharing the
  // link exports its future output — surfaced honestly in both panel states.
  const [hasAgent, setHasAgent] = useState(false);

  useEffect(() => {
    let alive = true;
    api
      .shareStatus(pageId)
      .then((s) => { if (alive) setStatus(s); })
      // A pre-share page (or an unreachable endpoint) reads as simply private.
      .catch(() => { if (alive) setStatus({ active: false, token: null, created_at: null }); });
    return () => { alive = false; };
  }, [pageId]);

  useEffect(() => {
    let alive = true;
    api
      .listAutomations()
      .then((r) => { if (alive) setHasAgent(r.automations.some((a) => a.page_id === pageId)); })
      // Can't tell → no disclosure (fail quiet); never a false "an agent writes here".
      .catch(() => {});
    return () => { alive = false; };
  }, [pageId]);

  const active = status?.active ?? false;
  const token = status?.token ?? null;
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const url = token ? `${origin}/share/${token}` : "";

  const create = async () => {
    setBusy(true);
    try {
      const s = await api.shareCreate(pageId);
      setStatus(s);
      onStateChange(s.active);
    } catch { /* keep the prior status; the panel stays usable */ }
    finally { setBusy(false); }
  };

  const revoke = async () => {
    setBusy(true);
    try {
      await api.shareRevoke(pageId);
      setStatus({ active: false, token: null, created_at: null });
      onStateChange(false);
    } catch { /* idempotent server-side; leave the panel as-is on failure */ }
    finally { setBusy(false); }
  };

  const copy = async () => {
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch { /* clipboard denied — the field is selectable as a fallback */ }
  };

  return (
    <>
      <aside
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Share this surface"
        onKeyDown={onKeyDown}
        className="fixed top-0 inset-x-0 sm:inset-x-auto sm:right-0 h-screen w-full sm:w-[320px] sm:max-w-[85vw] z-30 bg-[var(--surface)] border-l border-[var(--border)] shadow-2xl shadow-black/40 flex flex-col animate-slide-right"
      >
        <header className="flex items-center gap-2 px-4 h-14 border-b border-[var(--border)] shrink-0">
          <span className="text-[var(--muted)]"><Icon name="link" size={15} /></span>
          <span className="text-sm font-semibold tracking-tight">Share</span>
          <button ref={closeRef} type="button" onClick={onClose} aria-label="Close share"
            className="ml-auto text-[var(--muted)] hover:text-[var(--foreground)] w-6 h-6 grid place-items-center rounded">✕</button>
        </header>

        <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-4">
          {status === null ? (
            <p className="text-xs font-mono text-[var(--muted)]">Checking…</p>
          ) : !active ? (
            <>
              <div className="text-[11px] font-mono uppercase tracking-wide text-[var(--muted)]">Private</div>
              <p className="text-xs text-[var(--muted)] leading-relaxed">
                Anyone with the link can view this surface, read-only. Nothing else — no other pages, no profile.
              </p>
              {hasAgent && (
                <p className="text-[11px] font-mono text-[var(--muted)] leading-relaxed">
                  An agent writes to this page — its future output will be visible through this link.
                </p>
              )}
              <button type="button" onClick={create} disabled={busy}
                className="press w-full flex items-center justify-center gap-1.5 rounded-md bg-[var(--accent)] text-[var(--accent-fg)] px-3 py-1.5 text-sm font-medium hover:bg-[var(--accent-hover)] transition disabled:opacity-50">
                <Icon name="link" size={15} /> Create link
              </button>
            </>
          ) : (
            <>
              <div className="text-[11px] font-mono uppercase tracking-wide text-[var(--foreground)]">
                Link active <span className="text-[var(--muted)]">· {formatCreated(status?.created_at ?? null)}</span>
              </div>

              <div className="flex flex-col gap-1.5">
                <input
                  readOnly
                  value={url}
                  aria-label="Share link"
                  onFocus={(e) => e.currentTarget.select()}
                  className="w-full rounded-md border border-[var(--border)] bg-[var(--surface-elevated)] px-2.5 py-1.5 text-[11px] font-mono text-[var(--foreground)] truncate"
                />
                <button type="button" onClick={copy}
                  className="press w-full flex items-center justify-center gap-1.5 rounded-md bg-[var(--accent)] text-[var(--accent-fg)] px-3 py-1.5 text-sm font-medium hover:bg-[var(--accent-hover)] transition">
                  <Icon name={copied ? "check" : "link"} size={15} /> {copied ? "Copied" : "Copy link"}
                </button>
              </div>

              <div className="flex items-center gap-2">
                <button type="button" onClick={() => setConfirm("rotate")} disabled={busy}
                  className="flex-1 rounded-md border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--muted)] hover:text-[var(--foreground)] transition disabled:opacity-50">
                  Rotate link
                </button>
                <button type="button" onClick={() => setConfirm("revoke")} disabled={busy}
                  className="flex-1 rounded-md border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--danger)] hover:brightness-110 transition disabled:opacity-50">
                  Revoke
                </button>
              </div>

              <p className="text-[11px] text-[var(--muted)] leading-relaxed border-t border-[var(--border)] pt-3">
                This link shares the page&apos;s current and future contents, not a snapshot.
              </p>
              {hasAgent && (
                <p className="text-[11px] font-mono text-[var(--muted)] leading-relaxed">
                  An agent writes to this page — its future output will be visible through this link.
                </p>
              )}
            </>
          )}
        </div>
      </aside>

      <ConfirmDialog
        open={confirm !== null}
        title={confirm === "revoke" ? "Revoke this link?" : "Rotate this link?"}
        body={confirm === "revoke"
          ? "Anyone holding the current link loses access immediately."
          : "The old link stops working immediately."}
        confirmLabel={confirm === "revoke" ? "Revoke" : "Rotate"}
        onConfirm={() => { const c = confirm; setConfirm(null); if (c === "revoke") void revoke(); else void create(); }}
        onCancel={() => setConfirm(null)}
      />
    </>
  );
}
