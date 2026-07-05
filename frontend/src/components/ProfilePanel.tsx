"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { ProfileKind, UserProfileEntry } from "@/lib/types";
import { ConfirmDialog } from "./ConfirmDialog";

interface Props {
  onClose: () => void;
}

// Fixed display order + labels. Plural heads a group; singular labels the add-
// selector. Only non-empty groups render (an empty "Patterns" heading is noise).
const KINDS: { kind: ProfileKind; plural: string; one: string }[] = [
  { kind: "goal", plural: "Goals", one: "Goal" },
  { kind: "preference", plural: "Preferences", one: "Preference" },
  { kind: "pattern", plural: "Patterns", one: "Pattern" },
  { kind: "fact", plural: "Facts", one: "Fact" },
];

// R-801: a real surface where the owner can SEE, CORRECT, and DELETE what Trus
// believes about them. R-1306 dialog floor: role=dialog/aria-modal, Escape
// closes, focus enters the panel and is trapped inside while open (mirrors
// ConfirmDialog/EntryScreen). R-1305: matte charcoal, accent rationed to the
// one primary action (Add).
export function ProfilePanel({ onClose }: Props) {
  // null = still loading; [] = genuinely empty (drives the empty state).
  const [facts, setFacts] = useState<UserProfileEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [addKind, setAddKind] = useState<ProfileKind>("fact");
  const [addText, setAddText] = useState("");
  const asideRef = useRef<HTMLElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .profileList()
      .then((f) => alive && setFacts(f))
      .catch(() => alive && setFacts([]));
    return () => {
      alive = false;
    };
  }, []);

  // R-1306 focus contract: send focus into the panel on open, restore it to the
  // opener (the Profile button) on close.
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    return () => {
      if (prev?.isConnected) prev.focus();
    };
  }, []);

  // Escape + focus trap live on the ASIDE (bubble): when the clear-all
  // ConfirmDialog is open, focus sits in that SIBLING dialog, so these handlers
  // never fire — the dialog owns the keyboard (no duelling traps).
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key !== "Tab" || !asideRef.current) return;
    const nodes = asideRef.current.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    const list = Array.from(nodes).filter((el) => el.offsetParent !== null);
    if (list.length === 0) return;
    const first = list[0];
    const last = list[list.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };

  const submitAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = addText.trim();
    if (!text) return;
    setError(null);
    try {
      const entry = await api.profileAdd(addKind, text);
      // Backend dedups (owner+kind+text) and returns the existing row — merge by
      // id so a repeat add never shows a phantom duplicate.
      setFacts((f) => {
        const list = f ?? [];
        return list.some((x) => x.id === entry.id)
          ? list.map((x) => (x.id === entry.id ? entry : x))
          : [entry, ...list];
      });
      setAddText("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't add that fact.");
    }
  };

  const startEdit = (fact: UserProfileEntry) => {
    setEditingId(fact.id);
    setEditValue(fact.text);
  };

  const commitEdit = async (id: string) => {
    const text = editValue.trim();
    setEditingId(null);
    const fact = facts?.find((x) => x.id === id);
    if (!fact || !text || text === fact.text) return;
    setFacts((f) => (f ?? []).map((x) => (x.id === id ? { ...x, text } : x))); // optimistic
    setError(null);
    try {
      const updated = await api.profileUpdate(id, text);
      setFacts((f) => (f ?? []).map((x) => (x.id === id ? updated : x)));
    } catch (err) {
      setFacts((f) => (f ?? []).map((x) => (x.id === id ? fact : x))); // revert
      setError(err instanceof Error ? err.message : "Couldn't save that edit.");
    }
  };

  const handleDelete = async (id: string) => {
    const removed = facts?.find((x) => x.id === id) ?? null;
    setFacts((f) => (f ?? []).filter((x) => x.id !== id)); // optimistic
    setError(null);
    try {
      await api.profileDelete(id);
    } catch (err) {
      if (removed) setFacts((f) => [removed, ...(f ?? [])]); // restore on failure
      setError(err instanceof Error ? err.message : "Couldn't delete that fact.");
    }
  };

  const handleClear = async () => {
    setConfirmClear(false);
    const prev = facts ?? [];
    setFacts([]); // optimistic
    setError(null);
    try {
      await api.profileClear();
    } catch (err) {
      setFacts(prev); // restore on failure
      setError(err instanceof Error ? err.message : "Couldn't clear the profile.");
    }
  };

  const groups = KINDS.map((g) => ({
    ...g,
    items: (facts ?? []).filter((x) => x.kind === g.kind),
  })).filter((g) => g.items.length > 0);

  return (
    // ConfirmDialog is a SIBLING of <aside>, not nested inside it (2a-3 lesson):
    // the aside's slide animation makes it a containing block for position:fixed,
    // which would trap a nested dialog in the 320px column.
    <>
      {/* R-1304: full-width sheet below `sm` (the fixed 320px column would
          otherwise leave the canvas a sliver on a 375px phone) — same panel,
          same tokens/animation, just full-bleed on a narrow viewport. */}
      <aside
        ref={asideRef}
        role="dialog"
        aria-modal="true"
        aria-label="Profile — what Trus remembers about you"
        onKeyDown={onKeyDown}
        className="fixed top-0 inset-x-0 sm:inset-x-auto sm:right-0 h-screen w-full sm:w-[320px] sm:max-w-[85vw] z-30 bg-[var(--surface)] border-l border-[var(--border)] shadow-2xl shadow-black/40 flex flex-col animate-slide-right"
      >
        <header className="flex items-center gap-2 px-4 h-14 border-b border-[var(--border)] shrink-0">
          <span className="text-sm font-semibold tracking-tight">Profile</span>
          {facts !== null && <span className="text-xs text-[var(--muted)]">· {facts.length}</span>}
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Close profile"
            className="ml-auto text-[var(--muted)] hover:text-[var(--foreground)] w-6 h-6 grid place-items-center rounded"
          >
            ✕
          </button>
        </header>

        {/* Manual "add a fact" (R-801: the user can correct/add directly). */}
        <div className="p-3 border-b border-[var(--border)] flex flex-col gap-2">
          <form onSubmit={submitAdd} className="flex items-center gap-1.5">
            <select
              value={addKind}
              onChange={(e) => setAddKind(e.target.value as ProfileKind)}
              aria-label="Fact kind"
              className="shrink-0 rounded-md border border-[var(--border)] bg-[var(--surface-elevated)] text-xs text-[var(--muted)] px-1.5 py-1.5 focus:outline-none focus:border-[var(--accent)]"
            >
              {KINDS.map((g) => (
                <option key={g.kind} value={g.kind}>
                  {g.one}
                </option>
              ))}
            </select>
            <input
              value={addText}
              onChange={(e) => setAddText(e.target.value)}
              placeholder="Add something about you…"
              className="flex-1 min-w-0 bg-transparent text-sm placeholder:text-[var(--muted)] focus:outline-none"
            />
            <button
              type="submit"
              disabled={!addText.trim()}
              className="shrink-0 rounded-md bg-[var(--accent)] text-[var(--accent-fg)] px-2.5 py-1 text-xs font-medium hover:brightness-110 transition disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Add
            </button>
          </form>
          {error && <p className="text-xs text-[var(--danger)] px-0.5">{error}</p>}
        </div>

        <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-4">
          {facts === null ? (
            <p className="text-xs text-[var(--muted)] px-1 pt-2">Loading…</p>
          ) : facts.length === 0 ? (
            <p className="text-xs text-[var(--muted)] leading-relaxed px-1 pt-2">
              Trus hasn&apos;t learned anything about you yet — it will as you use it.
            </p>
          ) : (
            groups.map((g) => (
              <div key={g.kind} className="flex flex-col gap-2">
                <p className="text-[10px] uppercase tracking-wide text-[var(--muted)] font-mono px-1">
                  {g.plural}
                </p>
                {g.items.map((fact) => (
                  <div
                    key={fact.id}
                    className="rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] px-3 py-2 flex items-center gap-2"
                  >
                    {editingId === fact.id ? (
                      <input
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        onBlur={() => commitEdit(fact.id)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") commitEdit(fact.id);
                          if (e.key === "Escape") {
                            e.stopPropagation(); // keep Escape from closing the panel mid-edit
                            setEditingId(null);
                          }
                        }}
                        className="flex-1 min-w-0 bg-transparent text-sm border-b border-[var(--accent)] focus:outline-none"
                        autoFocus
                      />
                    ) : (
                      <button
                        type="button"
                        onClick={() => startEdit(fact)}
                        title="Click to edit"
                        className="flex-1 min-w-0 text-left text-sm break-words hover:text-[var(--accent)] transition"
                      >
                        {fact.text}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => handleDelete(fact.id)}
                      aria-label="Delete fact"
                      className="text-xs text-[var(--muted)] hover:text-[var(--danger)] transition shrink-0"
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            ))
          )}
        </div>

        {(facts?.length ?? 0) > 0 && (
          <div className="p-3 border-t border-[var(--border)] shrink-0">
            <button
              type="button"
              onClick={() => setConfirmClear(true)}
              className="w-full text-xs text-[var(--muted)] hover:text-[var(--danger)] transition py-1"
            >
              Delete everything Trus remembers
            </button>
          </div>
        )}
      </aside>

      <ConfirmDialog
        open={confirmClear}
        title="Delete everything Trus remembers about you?"
        body="This cannot be undone."
        confirmLabel="Delete everything"
        onConfirm={handleClear}
        onCancel={() => setConfirmClear(false)}
      />
    </>
  );
}
