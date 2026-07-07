"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { AutomationOut } from "@/lib/types";
import { approvalReducer, initialPulseState } from "@/lib/pulse";
import { useDialog } from "@/lib/useDialog";
import { ApprovalCard } from "./ApprovalCard";
import { ActivityRow } from "./ActivityRow";
import { AutomationRow } from "./AutomationRow";
import { ConfirmDialog } from "./ConfirmDialog";

interface Props {
  onClose: () => void;
  // A journal deep-link was tapped — close the panel and go to what it touched.
  onNavigate: (target: { moduleId?: string | null; pageId?: string | null }) => void;
  // Any mutation (approve/reject/run/delete) — nudge page.tsx to re-poll the count.
  onMutated: () => void;
}

const SectionLabel = ({ children }: { children: React.ReactNode }) => (
  <p className="font-mono text-[10px] uppercase tracking-wide text-[var(--muted)] px-1">{children}</p>
);

// THE trust surface — "Pulse": what happened, and what needs your tap. A
// right-side dialog aside (the ProfilePanel pattern: useDialog focus floor +
// animate-slide-right + full-width below sm). Self-fetching on open; owns its
// two live lists through the tested approvalReducer. Three stacked sections:
// NEEDS YOUR TAP (approval cards), ACTIVITY (the journal feed, keyset "load
// more"), and a collapsible AUTOMATIONS management section.
export function ActivityPanel({ onClose, onNavigate, onMutated }: Props) {
  const [state, dispatch] = useReducer(approvalReducer, undefined, initialPulseState);
  const [approvalsLoaded, setApprovalsLoaded] = useState(false);
  const [activityLoaded, setActivityLoaded] = useState(false);
  const [listError, setListError] = useState(false);
  const [automations, setAutomations] = useState<AutomationOut[] | null>(null);
  const [automationsOpen, setAutomationsOpen] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<AutomationOut | null>(null);

  const closeRef = useRef<HTMLButtonElement | null>(null);
  const { ref: asideRef, onKeyDown } = useDialog<HTMLElement>(true, onClose, closeRef);
  const focusClose = () => closeRef.current?.focus();

  // Fetch everything on open (mount IS open). Failures land honest states, never
  // a fabricated list.
  useEffect(() => {
    let alive = true;
    api
      .listApprovals()
      .then((r) => {
        if (!alive) return;
        dispatch({ type: "approvals/loaded", approvals: r.approvals });
        setApprovalsLoaded(true);
      })
      .catch(() => alive && (setListError(true), setApprovalsLoaded(true)));
    api
      .listActivity()
      .then((r) => {
        if (!alive) return;
        dispatch({ type: "activity/loaded", entries: r.entries, append: false });
        setActivityLoaded(true);
      })
      .catch(() => alive && (setListError(true), setActivityLoaded(true)));
    api
      .listAutomations()
      .then((r) => alive && setAutomations(r.automations))
      .catch(() => alive && setAutomations([]));
    return () => {
      alive = false;
    };
  }, []);

  // A 409 during a decision means the server truth diverged (double-tap /
  // expiry). Re-sync both lists, then lower the flag and nudge the count. The
  // flag is cleared in `finally` so a failed refetch can't loop.
  useEffect(() => {
    if (!state.needsRefetch) return;
    let alive = true;
    Promise.all([api.listApprovals(), api.listActivity()])
      .then(([ap, ac]) => {
        if (!alive) return;
        dispatch({ type: "approvals/loaded", approvals: ap.approvals });
        dispatch({ type: "activity/loaded", entries: ac.entries, append: false });
      })
      .catch(() => {})
      .finally(() => {
        if (!alive) return;
        dispatch({ type: "refetch/clear" });
        onMutated();
      });
    return () => {
      alive = false;
    };
  }, [state.needsRefetch, onMutated]);

  const decide = useCallback(
    async (id: string, mode: "approve" | "reject") => {
      dispatch({ type: "decision/submit", id, mode });
      try {
        const res = mode === "approve" ? await api.approve(id) : await api.reject(id);
        dispatch({ type: "decision/success", id, activity: res.activity });
        onMutated();
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          dispatch({ type: "decision/conflict", id }); // onMutated fires via the refetch effect
        } else {
          const detail =
            err instanceof ApiError && typeof err.detail === "string"
              ? err.detail
              : "something went wrong";
          dispatch({ type: "decision/error", id, error: detail });
        }
      }
    },
    [onMutated],
  );

  const loadMore = useCallback(async () => {
    const oldest = state.activity[state.activity.length - 1];
    if (loadingMore || state.activityDone || !oldest) return;
    setLoadingMore(true);
    try {
      const r = await api.listActivity(oldest.created_at);
      dispatch({ type: "activity/loaded", entries: r.entries, append: true });
    } catch {
      /* leave the button — a retry re-tries */
    } finally {
      setLoadingMore(false);
    }
  }, [state.activity, state.activityDone, loadingMore]);

  const patchDial = useCallback(async (a: AutomationOut, dial: number) => {
    const updated = await api.patchAutomation(a.id, { trust_dial: dial }); // throws → dial reverts
    setAutomations((list) => (list ?? []).map((x) => (x.id === a.id ? updated : x)));
  }, []);

  const toggle = useCallback(async (a: AutomationOut) => {
    setAutomations((list) => (list ?? []).map((x) => (x.id === a.id ? { ...x, enabled: !x.enabled } : x)));
    try {
      const updated = await api.patchAutomation(a.id, { enabled: !a.enabled });
      setAutomations((list) => (list ?? []).map((x) => (x.id === a.id ? updated : x)));
    } catch {
      setAutomations((list) => (list ?? []).map((x) => (x.id === a.id ? { ...x, enabled: a.enabled } : x)));
    }
  }, []);

  const runNow = useCallback(
    async (a: AutomationOut) => {
      try {
        const res = await api.runAutomation(a.id);
        if (res.activity) dispatch({ type: "activity/prepend", entry: res.activity });
        if (res.approval) {
          const ap = await api.listApprovals();
          dispatch({ type: "approvals/loaded", approvals: ap.approvals });
        }
        onMutated();
      } catch {
        /* run-now failed to reach the server — the row's spinner just clears */
      }
    },
    [onMutated],
  );

  const doDelete = useCallback(async () => {
    const a = confirmDelete;
    setConfirmDelete(null);
    window.setTimeout(focusClose, 0); // the row's Delete (dialog opener) unmounts
    if (!a) return;
    setAutomations((list) => (list ?? []).filter((x) => x.id !== a.id)); // optimistic
    try {
      await api.deleteAutomation(a.id);
      const ap = await api.listApprovals(); // DELETE cascade-expires pending approvals
      dispatch({ type: "approvals/loaded", approvals: ap.approvals });
      onMutated();
    } catch {
      setAutomations((list) => [a, ...(list ?? [])]); // restore
    }
  }, [confirmDelete, onMutated]);

  const pendingN = state.approvals.length;

  return (
    // ConfirmDialog is a SIBLING of the aside (the slide animation makes the
    // aside a containing block for position:fixed — ArchivedPanel.tsx lesson).
    <>
      <aside
        ref={asideRef}
        role="dialog"
        aria-modal="true"
        aria-label="Pulse — what happened and what needs your tap"
        onKeyDown={onKeyDown}
        className="fixed top-0 inset-x-0 sm:inset-x-auto sm:right-0 h-screen w-full sm:w-[340px] sm:max-w-[88vw] z-30 bg-[var(--surface)] border-l border-[var(--border)] shadow-2xl shadow-black/40 flex flex-col animate-slide-right"
      >
        <header className="flex items-center gap-2 px-4 h-14 border-b border-[var(--border)] shrink-0">
          <span className="text-sm font-semibold tracking-tight">Pulse</span>
          {pendingN > 0 && (
            <span className="font-mono text-xs" style={{ color: "var(--status-hold)" }}>
              · {pendingN}
            </span>
          )}
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Close Pulse"
            className="ml-auto text-[var(--muted)] hover:text-[var(--foreground)] w-6 h-6 grid place-items-center rounded"
          >
            ✕
          </button>
        </header>

        <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-5">
          {/* NEEDS YOUR TAP */}
          <section className="flex flex-col gap-2">
            <SectionLabel>
              <span style={pendingN > 0 ? { color: "var(--status-hold)" } : undefined}>
                needs your tap · {pendingN}
              </span>
            </SectionLabel>
            {!approvalsLoaded ? (
              <p className="text-xs text-[var(--muted)] px-1">Loading…</p>
            ) : listError && pendingN === 0 ? (
              <p className="text-xs text-[var(--muted)] px-1 leading-relaxed">
                Couldn&apos;t load approvals — reopen Pulse to try again.
              </p>
            ) : pendingN === 0 ? (
              <p className="text-xs text-[var(--muted)] px-1 leading-relaxed">Nothing waiting on you.</p>
            ) : (
              state.approvals.map((item, i) => (
                <ApprovalCard
                  key={item.approval.id}
                  item={item}
                  index={i}
                  onApprove={() => decide(item.approval.id, "approve")}
                  onDismiss={() => decide(item.approval.id, "reject")}
                />
              ))
            )}
          </section>

          {/* ACTIVITY */}
          <section className="flex flex-col gap-1">
            <SectionLabel>activity</SectionLabel>
            {!activityLoaded ? (
              <p className="text-xs text-[var(--muted)] px-1">Loading…</p>
            ) : state.activity.length === 0 ? (
              <p className="text-xs text-[var(--muted)] px-1 leading-relaxed">
                No activity yet — your automations will show up here as they run.
              </p>
            ) : (
              <>
                {state.activity.map((e, i) => (
                  <ActivityRow key={e.id} entry={e} index={i} onNavigate={onNavigate} />
                ))}
                {!state.activityDone && (
                  <button
                    type="button"
                    onClick={loadMore}
                    disabled={loadingMore}
                    className="mt-1 self-start text-[11px] text-[var(--muted)] hover:text-[var(--foreground)] transition disabled:opacity-60 px-1"
                  >
                    {loadingMore ? "Loading…" : "Load more"}
                  </button>
                )}
              </>
            )}
          </section>

          {/* AUTOMATIONS (collapsible) */}
          <section className="flex flex-col gap-2 border-t border-[var(--border)] pt-4">
            <button
              type="button"
              onClick={() => setAutomationsOpen((v) => !v)}
              aria-expanded={automationsOpen}
              className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wide text-[var(--muted)] hover:text-[var(--foreground)] transition px-1"
            >
              <span
                className="inline-block transition-transform"
                style={{ transform: automationsOpen ? "none" : "rotate(-90deg)" }}
                aria-hidden
              >
                ▾
              </span>
              automations{automations ? ` · ${automations.length}` : ""}
            </button>
            {automationsOpen &&
              (automations === null ? (
                <p className="text-xs text-[var(--muted)] px-1">Loading…</p>
              ) : automations.length === 0 ? (
                <p className="text-xs text-[var(--muted)] px-1 leading-relaxed">
                  No automations yet — Trus creates them as your workspace grows.
                </p>
              ) : (
                automations.map((a, i) => (
                  <AutomationRow
                    key={a.id}
                    automation={a}
                    index={i}
                    onPatchDial={(dial) => patchDial(a, dial)}
                    onToggle={() => toggle(a)}
                    onRun={() => runNow(a)}
                    onRequestDelete={() => setConfirmDelete(a)}
                  />
                ))
              ))}
          </section>
        </div>
      </aside>

      <ConfirmDialog
        open={confirmDelete !== null}
        title={`Delete "${confirmDelete?.name ?? ""}"?`}
        body="It stops running and its pending approvals are dismissed. This cannot be undone."
        confirmLabel="Delete"
        onConfirm={doDelete}
        onCancel={() => {
          setConfirmDelete(null);
          window.setTimeout(focusClose, 0);
        }}
      />
    </>
  );
}
