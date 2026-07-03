"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { Canvas } from "@/components/Canvas";
import { ConversationPanel } from "@/components/ConversationPanel";
import { ArchivedPanel } from "@/components/ArchivedPanel";
import { SnapshotsPanel } from "@/components/SnapshotsPanel";
import { Inspector } from "@/components/Inspector";
import { DetailView } from "@/components/DetailView";
import { Sidebar } from "@/components/Sidebar";
import { PromptBar } from "@/components/PromptBar";
import { AppearanceMenu } from "@/components/AppearanceMenu";
import { EmptyState } from "@/components/EmptyState";
import { CommandPalette, type Action } from "@/components/CommandPalette";
import { ShortcutsModal } from "@/components/ShortcutsModal";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { IntroSplash } from "@/components/IntroSplash";
import { InviteGate } from "@/components/InviteGate";
import { Icon } from "@/components/Icon";
import { api, ApiError } from "@/lib/api";
import { createModuleSaver, type SaveStatus } from "@/lib/moduleSaver";
import { useAppearance } from "@/lib/appearance";
import { resolveIconName } from "@/lib/theme";
import type { CommitModule, Message, Page, Snapshot, StoredModule } from "@/lib/types";

function HeaderInsights({
  activePageId,
  onNewModule,
}: {
  activePageId?: string;
  onNewModule: (m: StoredModule) => void;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api.workspaceInsights(activePageId);
      if (r.module) onNewModule(r.module);
    } catch (err) {
      const msg =
        err instanceof ApiError && err.refusal
          ? err.refusal
          : err instanceof ApiError && err.question
            ? err.question // R-304: surface the clarifying question, not raw JSON
            : err instanceof Error
              ? err.message
              : "Could not generate insights.";
      setError(msg);
      setTimeout(() => setError(null), 4000);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={run}
        disabled={loading}
        className="shrink-0 flex items-center gap-1.5 rounded-md border border-[var(--border)] px-2.5 py-1 text-xs text-[var(--muted)] hover:text-[var(--foreground)] transition disabled:opacity-40"
        title="Generate a dashboard that aggregates this tab's modules"
      >
        <Icon name="sparkles" size={14} className={loading ? "animate-pulse" : ""} />
        <span className="hidden sm:inline">{loading ? "Synthesizing…" : "Insights"}</span>
      </button>
      {error && (
        <div className="fixed top-16 left-1/2 -translate-x-1/2 z-30 rounded-lg bg-[var(--surface)] border border-[var(--danger)] px-3 py-1.5 text-xs text-[var(--danger)] shadow">
          {error}
        </div>
      )}
    </>
  );
}

export default function Home() {
  const [pages, setPages] = useState<Page[]>([]);
  const [activePageId, setActivePageId] = useState<string | null>(null);
  const [modules, setModules] = useState<StoredModule[]>([]);
  const [loading, setLoading] = useState(true);
  const [refineTarget, setRefineTarget] = useState<StoredModule | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // The inspector (side popup) is intentionally separate from selection: clicking
  // a module only selects/highlights it; the inspector opens solely via the pen.
  const [inspectorId, setInspectorId] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [convoOpen, setConvoOpen] = useState(false);
  const [seed, setSeed] = useState<string | null>(null);
  const [showWelcome, setShowWelcome] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [archivedOpen, setArchivedOpen] = useState(false);
  const [archived, setArchived] = useState<StoredModule[]>([]);
  const [snapshotsOpen, setSnapshotsOpen] = useState(false);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  // R-1102: page delete is the most destructive action (cascades every module
  // on the page) — always confirmed, stating the module count. Holds the page
  // plus its real module ids: `modules` state only covers the ACTIVE page,
  // but any sidebar row can be deleted, so the ids are fetched per-page.
  const [pageDeleteConfirm, setPageDeleteConfirm] = useState<{ page: Page; moduleIds: string[]; archivedCount: number } | null>(null);
  const [cmdOpen, setCmdOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [allModules, setAllModules] = useState<StoredModule[]>([]);
  const [focusReq, setFocusReq] = useState<{ id: string; n: number } | undefined>(undefined);
  const [fitReq, setFitReq] = useState(0);
  const [promptFocus, setPromptFocus] = useState(0);
  const [introOpen, setIntroOpen] = useState(false);
  // R-901: unclaimed sessions (prod, anon off) see the gate instead of the
  // canvas. `identityName` powers the header identity chip once claimed.
  const [gated, setGated] = useState(false);
  const [identityName, setIdentityName] = useState<string | null>(null);
  const pendingFocusRef = useRef<string | null>(null);
  const { theme, setTheme } = useAppearance();
  // R-602 (cross-tab half): a low-drama toast surface reused for cross-tab
  // events — a stale write losing a rev race, a module deleted elsewhere (404),
  // or an unreadable snapshot. Not an error banner; nothing was lost silently.
  const [conflictNotice, setConflictNotice] = useState<string | null>(null);
  const conflictTimerRef = useRef<number | null>(null);
  const flashNotice = useCallback((message: string) => {
    setConflictNotice(message);
    // Reset the dismiss timer per flash: a second notice within 4s must get
    // its own full display window, not be cut short by the first one's timer.
    if (conflictTimerRef.current !== null) window.clearTimeout(conflictTimerRef.current);
    conflictTimerRef.current = window.setTimeout(() => setConflictNotice(null), 4000);
  }, []);

  // Always-fresh handle on `modules` for the saver's `getRev` (the saver is
  // created once via useMemo below, so it can't close over state directly).
  const modulesRef = useRef<StoredModule[]>(modules);
  useEffect(() => {
    modulesRef.current = modules;
  }, [modules]);

  // R-601/R-602: a single writer owns all module persistence. `commitModule`
  // updates the parent modules array synchronously (optimistic — a metric bound
  // to another module recomputes on the same render pass), then hands the config
  // to the saver, which debounces, coalesces, serializes one in-flight PATCH per
  // module, retries failures with backoff, and exposes a save status.
  const saver = useMemo(
    () =>
      createModuleSaver({
        patch: (id, c, rev) => api.patchModule(id, c, rev),
        // R-1101: best-effort flush that survives a page unload (keepalive fetch).
        patchKeepalive: (id, c, rev) => api.patchModuleKeepalive(id, c, rev),
        getRev: (id) => modulesRef.current.find((m) => m.id === id)?.rev,
        // Reconcile server metadata only — never overwrite config, which may
        // already hold a newer local edit (overwriting would revert a keystroke).
        onSaved: (m) =>
          setModules((ms) =>
            ms.map((x) => (x.id === m.id ? { ...x, updated_at: m.updated_at, rev: m.rev } : x)),
          ),
        onError: (id, err) => console.error("Failed to save module", id, err),
        // R-602: a stale PATCH lost the rev race — replace with the current
        // module (the pending edit was already dropped by the saver) and
        // surface it visibly rather than silently discarding the edit.
        onConflict: (current) => {
          setModules((ms) => ms.map((x) => (x.id === current.id ? current : x)));
          flashNotice("This module changed in another tab — showing the latest version.");
        },
        // R-602 backlog: a PATCH 404'd — the module was deleted elsewhere. The
        // saver has already forgotten it; drop it from the canvas and say so
        // instead of retrying a write that can never land.
        onMissing: (id) => {
          setModules((ms) => ms.filter((x) => x.id !== id));
          flashNotice("That module no longer exists — it was removed elsewhere.");
        },
      }),
    [flashNotice],
  );
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle");
  useEffect(() => {
    setSaveStatus(saver.status());
    return saver.subscribe(() => setSaveStatus(saver.status()));
  }, [saver]);
  // Don't lose an in-flight edit if the tab closes mid-save. A normal fetch is
  // cancelled the instant the document tears down, so flushAll() alone would
  // drop the very edit it means to save — flushAllKeepalive re-fires each
  // pending config through a keepalive fetch that outlives the page, and we
  // still raise the "unsaved changes" prompt as a belt-and-braces warning.
  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (saver.status() !== "idle") {
        saver.flushAllKeepalive();
        e.preventDefault();
        e.returnValue = ""; // legacy browsers require this to show the prompt
      }
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [saver]);
  const commitModule = useCallback<CommitModule>(
    (id, configOrUpdater, delay) => {
      // The saver needs the COMPUTED config, but React's setModules updater runs
      // async — its result can't be read back synchronously here. Derive it from
      // the always-fresh modulesRef instead, and keep that ref in lock-step so a
      // second commit in the SAME tick chains off this result rather than a
      // stale props snapshot (the same-tick stale-closure class, R-602).
      const current = modulesRef.current.find((m) => m.id === id)?.config;
      const next =
        typeof configOrUpdater === "function"
          ? current
            ? configOrUpdater(current)
            : undefined // updater form for a module no longer in state — nothing to do
          : configOrUpdater;
      if (next === undefined) return;
      modulesRef.current = modulesRef.current.map((m) => (m.id === id ? { ...m, config: next } : m));
      setModules((ms) => ms.map((m) => (m.id === id ? { ...m, config: next } : m)));
      saver.commit(id, next, delay);
    },
    [saver],
  );

  useEffect(() => {
    if (!sessionStorage.getItem("trus-intro-seen")) setIntroOpen(true);
  }, []);
  const dismissIntro = useCallback(() => {
    setIntroOpen(false);
    sessionStorage.setItem("trus-intro-seen", "1");
    setPromptFocus((n) => n + 1);
  }, []);

  useEffect(() => {
    setSidebarCollapsed(localStorage.getItem("trus-sidebar-collapsed") === "1");
  }, []);
  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed((v) => {
      const next = !v;
      localStorage.setItem("trus-sidebar-collapsed", next ? "1" : "0");
      return next;
    });
  }, []);

  const reloadConvo = useCallback((pageId: string | null) => {
    if (!pageId) {
      setMessages([]);
      return;
    }
    api.listConversation(pageId).then(setMessages).catch(() => {});
  }, []);

  // Check invite-claim status first (R-901): an unclaimed session (prod, anon
  // off) gets the gate instead of the canvas, before any workspace data loads.
  // Then load pages, then modules + conversation for the first page. The
  // outer catch is belt-and-braces: a 401 from the data loads themselves
  // (e.g. the session was revoked mid-flight) also swaps to the gate.
  useEffect(() => {
    let firstId: string | null = null;
    api
      .authMe()
      .then((me) => {
        setIdentityName(me.name);
        if (!me.claimed) {
          setGated(true);
          setLoading(false);
          return null;
        }
        return api
          .listPages()
          .then((list) => {
            setPages(list);
            firstId = list[0]?.id ?? null;
            if (firstId) setActivePageId(firstId);
            return firstId ? api.listModules(firstId) : Promise.resolve([] as StoredModule[]);
          })
          .then(async (mods) => {
            // Pre-populate a brand-new workspace once (never reseed after clearing).
            if (mods.length === 0 && firstId && !localStorage.getItem("trus-seeded")) {
              try {
                const seeded = await api.seedStarter(firstId);
                localStorage.setItem("trus-seeded", "1");
                setModules(seeded);
                setShowWelcome(true);
              } catch {
                setModules(mods);
              }
            } else {
              setModules(mods);
            }
            if (firstId) reloadConvo(firstId);
          })
          .finally(() => setLoading(false));
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          setGated(true);
        } else {
          console.error("Failed to load workspace", err);
        }
        setLoading(false);
      });
  }, [reloadConvo]);

  // Reload modules + conversation whenever active page changes (not on first mount).
  const [firstLoad, setFirstLoad] = useState(true);
  useEffect(() => {
    if (firstLoad) { setFirstLoad(false); return; }
    if (!activePageId) return;
    setModules([]);
    setSelectedId(null);
    setInspectorId(null);
    setDetailId(null);
    api
      .listModules(activePageId)
      .then((list) => {
        setModules(list);
        if (pendingFocusRef.current) {
          const id = pendingFocusRef.current;
          pendingFocusRef.current = null;
          setSelectedId(id);
          setFocusReq({ id, n: Date.now() });
        }
      })
      .catch((err) => console.error("Failed to load modules for page", err));
    reloadConvo(activePageId);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activePageId]);

  const handleNewModule = useCallback((m: StoredModule) => {
    setModules((prev) => {
      // The model/stub doesn't pick good canvas coordinates (it tends to emit
      // 0,0), so we place new modules ourselves in a tidy non-overlapping grid
      // that clears the header. The user can drag them anywhere after.
      const PER_ROW = 3, GAP_X = 396, GAP_Y = 480, X0 = 32, Y0 = 96;
      const i = prev.length;
      const placed: StoredModule = {
        ...m,
        config: {
          ...m.config,
          layout: {
            ...m.config.layout,
            // Cap width so new tools tile cleanly without overlapping (wide tables
            // scroll horizontally; the user can still resize bigger afterward).
            width: Math.min(m.config.layout.width || 372, 372),
            height: 0, // content-sized — no wasted vertical space until resized
            x: X0 + (i % PER_ROW) * GAP_X,
            y: Y0 + Math.floor(i / PER_ROW) * GAP_Y,
          },
        },
      };
      // Route through the single writer (R-601/R-602) instead of a one-shot
      // PATCH: `prev` already carries the placed layout into `modules` here,
      // so only the saver's debounced persist (delay 0 — placement should
      // land immediately) is needed, not the full commitModule/setModules path.
      saver.commit(placed.id, placed.config, 0);
      return [...prev, placed];
    });
    reloadConvo(activePageId);
    setShowWelcome(false);
    // Frame the freshly-generated tool(s) — auto zoom/pan to fit. Deferred so the
    // content-sized card has mounted and reported its real height first.
    window.setTimeout(() => setFitReq((n) => n + 1), 160);
  }, [activePageId, reloadConvo, saver]);

  const handleModuleChange = useCallback((updated: StoredModule) => {
    setModules((prev) => prev.map((m) => (m.id === updated.id ? updated : m)));
  }, []);

  const handleUndoModule = useCallback(async (id: string) => {
    try {
      const reverted = await api.undoModule(id);
      setModules((prev) => prev.map((m) => (m.id === id ? reverted : m)));
    } catch {
      // 409 = nothing to undo
    }
  }, []);

  const handleSelectForRefine = useCallback(
    (id: string) => setRefineTarget(modules.find((m) => m.id === id) ?? null),
    [modules],
  );

  const handleClearRefine = useCallback(() => setRefineTarget(null), []);

  const handleExpand = useCallback((id: string) => {
    setDetailId(id);
    setSelectedId(id);
    setConvoOpen(false);
    setArchivedOpen(false);
    setSnapshotsOpen(false);
  }, []);

  const handleRefinedModule = useCallback((updated: StoredModule) => {
    setModules((prev) => prev.map((m) => (m.id === updated.id ? updated : m)));
    setRefineTarget(null);
    reloadConvo(activePageId);
  }, [activePageId, reloadConvo]);

  // Page handlers
  const handleSelectPage = useCallback((id: string) => {
    setActivePageId(id);
    setRefineTarget(null);
  }, []);

  const handleCreatePage = useCallback(async (parentId?: string | null) => {
    try {
      const page = await api.createPage(`Page ${pages.length + 1}`, undefined, parentId ?? undefined);
      setPages((prev) => [...prev, page]);
      setActivePageId(page.id);
      setModules([]);
      setMessages([]);
      setRefineTarget(null);
    } catch (err) {
      console.error("Failed to create page", err);
    }
  }, [pages.length]);

  const handleRenamePage = useCallback(async (id: string, name: string) => {
    try {
      const p = await api.updatePage(id, { name });
      setPages((prev) => prev.map((x) => (x.id === id ? p : x)));
    } catch (err) {
      console.error("Failed to rename page", err);
    }
  }, []);

  const handleSetPageIcon = useCallback(async (id: string, icon: string) => {
    try {
      const p = await api.updatePage(id, { icon });
      setPages((prev) => prev.map((x) => (x.id === id ? p : x)));
    } catch (err) {
      console.error("Failed to set page icon", err);
    }
  }, []);

  const handleReorderPages = useCallback(async (orderedIds: string[]) => {
    setPages((prev) => orderedIds.map((id) => prev.find((p) => p.id === id)).filter(Boolean) as Page[]);
    try {
      const updated = await api.reorderPages(orderedIds);
      setPages(updated);
    } catch (err) {
      console.error("Failed to reorder pages", err);
    }
  }, []);

  // R-1102: Sidebar only requests the delete; this opens the confirm dialog
  // stating the module count. The actual delete happens in handleConfirmDeletePage.
  // The target page's modules are fetched here (before the dialog opens) — the
  // local `modules` state only holds the active page's, and the sidebar's ✕
  // works on every row, so counting/forgetting from local state would report
  // "0 modules" and skip the forget-sweep for any non-active page.
  const handleRequestDeletePage = useCallback(async (page: Page) => {
    let moduleIds: string[];
    let archivedCount = 0;
    try {
      // R-1102: the FK cascade drops ARCHIVED modules on this page too, so count
      // them honestly (include_archived) — the confirm must not undercount, and the
      // forget-sweep must clear pending state for archived ids as well.
      const all = await api.listModules(page.id, true);
      moduleIds = all.map((m) => m.id);
      archivedCount = all.filter((m) => m.archived).length;
    } catch {
      // Fetch failed — fall back to what we know locally (exact for the
      // active page, best-effort otherwise) rather than blocking the delete.
      moduleIds = modulesRef.current.filter((m) => m.page_id === page.id).map((m) => m.id);
    }
    setPageDeleteConfirm({ page, moduleIds, archivedCount });
  }, []);

  const handleCancelDeletePage = useCallback(() => setPageDeleteConfirm(null), []);

  const handleConfirmDeletePage = useCallback(async () => {
    const req = pageDeleteConfirm;
    if (!req) return;
    setPageDeleteConfirm(null);
    // Cascading delete: the server drops every module on this page (FK
    // cascade) — forget any pending saves too, so a debounced PATCH can't
    // fire against a module that's about to vanish.
    req.moduleIds.forEach((id) => saver.forget(id));
    try {
      await api.deletePage(req.page.id);
    } catch {
      return; // last page (409) or not found
    }
    setModules((prev) => prev.filter((m) => m.page_id !== req.page.id));
    setPages((prev) => {
      const remaining = prev.filter((p) => p.id !== req.page.id);
      setActivePageId((cur) => (cur === req.page.id ? remaining[remaining.length - 1]?.id ?? null : cur));
      return remaining;
    });
  }, [pageDeleteConfirm, saver]);

  // Conversation handlers
  const handleReusePrompt = useCallback((text: string) => {
    setSeed(text);
    setConvoOpen(false);
  }, []);

  const handleSeedConsumed = useCallback(() => setSeed(null), []);

  const handlePickChip = useCallback((text: string) => setSeed(text), []);

  const handleClearConversation = useCallback(() => {
    if (!activePageId) return;
    api.clearConversation(activePageId).then(() => setMessages([])).catch(() => {});
  }, [activePageId]);

  // Module lifecycle: duplicate / archive / restore
  const handleDuplicateModule = useCallback(async (id: string) => {
    try {
      const dup = await api.duplicateModule(id);
      setModules((prev) => [...prev, dup]);
      setSelectedId(dup.id);
      setInspectorId(dup.id);
    } catch (err) {
      console.error("Failed to duplicate module", err);
    }
  }, []);

  const handleArchiveModule = useCallback(async (id: string) => {
    saver.forget(id); // drop any pending save for a module leaving the canvas
    setModules((prev) => prev.filter((m) => m.id !== id));
    setSelectedId((cur) => (cur === id ? null : cur));
    setInspectorId((cur) => (cur === id ? null : cur));
    try { await api.archiveModule(id); } catch (err) { console.error("Failed to archive", err); }
  }, [saver]);

  const openArchived = useCallback(async () => {
    setSelectedId(null);
    setInspectorId(null);
    setConvoOpen(false);
    setSnapshotsOpen(false);
    try { setArchived(await api.listArchived()); } catch { setArchived([]); }
    setArchivedOpen(true);
  }, []);

  const handleRestoreModule = useCallback(async (id: string) => {
    try {
      const m = await api.restoreModule(id);
      setArchived((prev) => prev.filter((x) => x.id !== id));
      setModules((prev) => (!m.page_id || m.page_id === activePageId ? [...prev, m] : prev));
    } catch (err) {
      console.error("Failed to restore module", err);
    }
  }, [activePageId]);

  const handleDeleteArchived = useCallback(async (id: string) => {
    setArchived((prev) => prev.filter((x) => x.id !== id));
    try { await api.deleteModule(id); } catch (err) { console.error("Failed to delete", err); }
  }, []);

  // Snapshots
  const openSnapshots = useCallback(async () => {
    if (!activePageId) return;
    setSelectedId(null);
    setInspectorId(null);
    setConvoOpen(false);
    setArchivedOpen(false);
    try { setSnapshots(await api.listSnapshots(activePageId)); } catch { setSnapshots([]); }
    setSnapshotsOpen(true);
  }, [activePageId]);

  const handleSaveSnapshot = useCallback(async () => {
    if (!activePageId) return;
    const label = new Date().toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    try {
      const s = await api.createSnapshot(activePageId, label);
      setSnapshots((prev) => [s, ...prev]);
    } catch (err) { console.error("Failed to save snapshot", err); }
  }, [activePageId]);

  const handleRestoreSnapshot = useCallback(async (id: string) => {
    if (!activePageId) return;
    try {
      await api.restoreSnapshot(id);
      const list = await api.listModules(activePageId);
      setModules(list);
      setSelectedId(null);
    } catch (err) {
      // 2a-4 backlog: a 409 means the stored snapshot is corrupt and the server
      // restored nothing — surface it on the shared notice instead of failing
      // silently in the console.
      if (err instanceof ApiError && err.status === 409) {
        flashNotice("This snapshot is unreadable — nothing was restored.");
      } else {
        console.error("Failed to restore snapshot", err);
      }
    }
  }, [activePageId, flashNotice]);

  const handleDeleteSnapshot = useCallback(async (id: string) => {
    setSnapshots((prev) => prev.filter((s) => s.id !== id));
    try { await api.deleteSnapshot(id); } catch (err) { console.error("Failed to delete snapshot", err); }
  }, []);

  // Command palette / search jump-to
  const handleGoToPage = useCallback((id: string) => { setActivePageId(id); setCmdOpen(false); }, []);
  const handleGoToModule = useCallback((m: StoredModule) => {
    setCmdOpen(false);
    setConvoOpen(false);
    setArchivedOpen(false);
    if (m.page_id && m.page_id !== activePageId) {
      pendingFocusRef.current = m.id; // applied once the page's modules load
      setActivePageId(m.page_id);
    } else {
      setSelectedId(m.id);
      setFocusReq({ id: m.id, n: Date.now() });
    }
  }, [activePageId]);

  // Load all modules across pages for cross-page search when the palette opens.
  useEffect(() => {
    if (cmdOpen) api.listModules().then(setAllModules).catch(() => setAllModules([]));
  }, [cmdOpen]);

  const actions: Action[] = useMemo(() => [
    { id: "new-tool", label: "New tool…", hint: "creation bar", run: () => setPromptFocus((n) => n + 1) },
    { id: "new-page", label: "New page", run: () => handleCreatePage(null) },
    { id: "theme", label: `Switch to ${theme === "dark" ? "light" : "dark"} theme`, run: () => setTheme(theme === "dark" ? "light" : "dark") },
    { id: "fit", label: "Fit canvas to content", run: () => setFitReq((n) => n + 1) },
    { id: "sidebar", label: "Toggle sidebar", run: toggleSidebar },
    { id: "archived", label: "Open archived", run: openArchived },
    { id: "shortcuts", label: "Keyboard shortcuts", run: () => setShortcutsOpen(true) },
  ], [theme, setTheme, handleCreatePage, toggleSidebar, openArchived]);

  // Global keyboard shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      const el = e.target as HTMLElement | null;
      const typing = !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
      if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); setCmdOpen((o) => !o); return; }
      if (mod && e.key === "\\") { e.preventDefault(); toggleSidebar(); return; }
      if (mod && e.key === "/") { e.preventDefault(); setPromptFocus((n) => n + 1); return; }
      if (mod && e.key.toLowerCase() === "d" && selectedId) { e.preventDefault(); handleDuplicateModule(selectedId); return; }
      if (mod && e.key.toLowerCase() === "z" && selectedId && !typing) { e.preventDefault(); handleUndoModule(selectedId); return; }
      if (e.key === "Escape") { setCmdOpen(false); setShortcutsOpen(false); setArchivedOpen(false); setSnapshotsOpen(false); setDetailId(null); setSelectedId(null); setInspectorId(null); setConvoOpen(false); return; }
      if (!typing && !mod) {
        if (e.key === "?" || (e.shiftKey && e.key === "/")) setShortcutsOpen(true);
        else if (e.key.toLowerCase() === "f") setFitReq((n) => n + 1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedId, toggleSidebar, handleDuplicateModule, handleUndoModule]);

  const activeModules = modules.filter((m) => !m.page_id || m.page_id === activePageId);
  const activePage = pages.find((p) => p.id === activePageId) ?? null;
  const inspectorModule = activeModules.find((m) => m.id === inspectorId) ?? null;
  const detailModule = activeModules.find((m) => m.id === detailId) ?? null;

  const statusText = loading
    ? "Loading…"
    : activeModules.length === 0
      ? "Empty canvas"
      : `${activeModules.length} module${activeModules.length === 1 ? "" : "s"}`;

  // Breadcrumb trail: the active page up through its parents (PRD 5.2).
  const trail: Page[] = [];
  {
    let cur: Page | null = activePage;
    let guard = 0;
    while (cur && guard++ < 50) {
      trail.unshift(cur);
      const parentId = cur.parent_id;
      cur = parentId ? pages.find((p) => p.id === parentId) ?? null : null;
    }
  }

  if (gated) {
    return <InviteGate />;
  }

  return (
    <div className="flex h-screen w-full">
      <Sidebar
        pages={pages}
        activePageId={activePageId}
        collapsed={sidebarCollapsed}
        onToggleCollapse={toggleSidebar}
        onSelect={handleSelectPage}
        onCreate={handleCreatePage}
        onRename={handleRenamePage}
        onSetIcon={handleSetPageIcon}
        onDelete={handleRequestDeletePage}
        onReorder={handleReorderPages}
        onOpenArchived={openArchived}
        onOpenSnapshots={openSnapshots}
      />
      <main className="flex-1 flex flex-col relative min-w-0">
      <header className="absolute top-0 inset-x-0 z-20 h-14 px-4 sm:px-5 flex items-center gap-3 border-b border-[var(--border)] bg-[var(--background)]/85 backdrop-blur">
        <div className="flex items-center gap-1.5 min-w-0">
          {trail.map((p, i) => (
            <span key={p.id} className="flex items-center gap-1.5 min-w-0">
              {i > 0 && <span className="text-[var(--muted)] text-xs shrink-0">›</span>}
              <button
                type="button"
                onClick={() => handleSelectPage(p.id)}
                className={`flex items-center gap-1.5 min-w-0 ${i === trail.length - 1 ? "text-[var(--foreground)] font-semibold" : "text-[var(--muted)] hover:text-[var(--foreground)]"}`}
              >
                <span className="shrink-0" style={{ color: i === trail.length - 1 ? "var(--accent)" : undefined }}>
                  <Icon name={resolveIconName(p.icon, p.name)} size={15} />
                </span>
                <span className="truncate text-sm tracking-tight">{p.name}</span>
              </button>
            </span>
          ))}
          <span className="hidden lg:inline text-xs text-[var(--muted)] ml-1 shrink-0">· {statusText}</span>
        </div>

        <div className="flex-1 flex justify-center px-2 min-w-0">
          <button
            type="button"
            onClick={() => setCmdOpen(true)}
            className="w-full max-w-[360px] flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface)]/60 px-3 py-1.5 text-xs text-[var(--muted)] hover:text-[var(--foreground)] hover:border-[var(--accent)] transition"
            aria-label="Search and commands"
          >
            <Icon name="search" size={14} />
            <span className="flex-1 text-left truncate">Search or run a command…</span>
            <kbd className="hidden sm:inline font-mono text-[10px] rounded border border-[var(--border)] px-1">⌘K</kbd>
          </button>
        </div>

        {activeModules.length >= 2 && (
          <HeaderInsights activePageId={activePageId ?? undefined} onNewModule={handleNewModule} />
        )}

        <button
          type="button"
          onClick={() => setConvoOpen((v) => { const n = !v; if (n) { setSelectedId(null); setInspectorId(null); setArchivedOpen(false); setSnapshotsOpen(false); } return n; })}
          className={`shrink-0 flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs transition ${
            convoOpen
              ? "border-[var(--accent)] text-[var(--foreground)]"
              : "border-[var(--border)] text-[var(--muted)] hover:text-[var(--foreground)]"
          }`}
          title="Conversation history for this tab"
          aria-label="Toggle history"
        >
          <Icon name="clock" size={14} />
          <span className="hidden sm:inline">History</span>
          {messages.length > 0 && (
            <span className="rounded-full bg-[var(--surface-elevated)] text-[var(--muted)] px-1.5 leading-tight">
              {messages.filter((m) => m.role === "user").length}
            </span>
          )}
        </button>

        <Link
          href="/studio"
          className="shrink-0 flex items-center gap-1.5 rounded-md border border-[var(--border)] px-2.5 py-1 text-xs text-[var(--muted)] hover:text-[var(--foreground)] transition"
          title="Layout Studio — browse layout patterns per use case"
        >
          <Icon name="grid" size={14} />
          <span className="hidden sm:inline">Studio</span>
        </Link>

        {identityName && (
          <span
            className="hidden sm:inline-flex shrink-0 items-center rounded-md border border-[var(--border)] px-2.5 py-1 text-xs text-[var(--muted)]"
            title={`Signed in as ${identityName}`}
          >
            {identityName}
          </span>
        )}

        <AppearanceMenu />
      </header>

      {/* Save-status pill (R-602). Ethos: Geist Mono "machine" register, sentence
          case, restrained — the muted "Saving…" carries no accent (magenta is
          rationed for the one primary action); errors use the muted terracotta
          status token (--danger / --status-err-dim), never neon red. */}
      {saveStatus !== "idle" && (
        <div
          role="status"
          aria-live="polite"
          className={`absolute top-16 left-4 z-30 flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-mono tracking-wide backdrop-blur transition-colors ${
            saveStatus === "error"
              ? "border-[var(--danger)] text-[var(--danger)] bg-[var(--status-err-dim)]"
              : "border-[var(--border)] text-[var(--muted)] bg-[var(--surface)]/90"
          }`}
        >
          {saveStatus === "error" ? (
            <>
              <span aria-hidden>⚠</span>
              <span>Not saved — retrying</span>
            </>
          ) : (
            <>
              <span aria-hidden className="w-1.5 h-1.5 rounded-full bg-[var(--muted)] animate-pulse" />
              <span>Saving…</span>
            </>
          )}
        </div>
      )}

      {/* R-602 conflict toast: a stale write lost a rev race against another
          tab. Same surface/style as the Studio toast — a neutral, low-drama
          notice, not an error banner (nothing was lost, just superseded). */}
      {conflictNotice && (
        <div
          role="status"
          aria-live="polite"
          className="fixed bottom-5 left-1/2 -translate-x-1/2 z-30 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 py-2 text-sm shadow-lg animate-pop"
        >
          {conflictNotice}
        </div>
      )}

      <Canvas
        modules={activeModules}
        activePageId={activePageId ?? undefined}
        selectedId={selectedId}
        onModuleSelect={(id) => { setSelectedId(id); setInspectorId(null); if (id) { setConvoOpen(false); setArchivedOpen(false); setSnapshotsOpen(false); } }}
        onModuleEdit={(id) => { setSelectedId(id); setInspectorId(id); setConvoOpen(false); setArchivedOpen(false); setSnapshotsOpen(false); }}
        onModuleExpand={handleExpand}
        onModuleChange={handleModuleChange}
        onModuleCommit={commitModule}
        onModuleArchive={handleArchiveModule}
        onModuleUndo={handleUndoModule}
        onModuleSelectForRefine={handleSelectForRefine}
        focusRequest={focusReq}
        fitRequest={fitReq}
      />

      {!loading && activeModules.length === 0 && <EmptyState onPick={handlePickChip} />}

      {showWelcome && (
        <div className="absolute top-[4.5rem] left-1/2 -translate-x-1/2 z-20 flex items-center gap-2.5 rounded-xl border border-[var(--border)] bg-[var(--surface)]/95 backdrop-blur px-4 py-2.5 shadow-lg max-w-[90vw] animate-pop">
          <span className="shrink-0 text-[var(--accent)]"><Icon name="sparkles" size={16} /></span>
          <span className="text-sm">
            This is your space. Tell me what you&apos;d like to organize, or edit what&apos;s here.
          </span>
          <button
            type="button"
            onClick={() => setShowWelcome(false)}
            className="text-[var(--muted)] hover:text-[var(--foreground)] transition shrink-0"
            aria-label="Dismiss welcome"
          >
            ✕
          </button>
        </div>
      )}

      <PromptBar
        onModule={handleNewModule}
        activePageId={activePageId ?? undefined}
        refineTarget={refineTarget}
        onRefineModule={handleRefinedModule}
        onClearRefine={handleClearRefine}
        seed={seed}
        onSeedConsumed={handleSeedConsumed}
        focusSignal={promptFocus}
      />

      {convoOpen && (
        <ConversationPanel
          messages={messages}
          pageName={activePage?.name ?? "this tab"}
          onClose={() => setConvoOpen(false)}
          onClear={handleClearConversation}
          onReuse={handleReusePrompt}
        />
      )}

      {detailModule && (
        <DetailView
          module={detailModule}
          crossModuleValues={{}}
          inspectorOpen={!!inspectorModule}
          onClose={() => setDetailId(null)}
          onCommit={commitModule}
          onUndo={handleUndoModule}
          onRefine={(id) => { handleSelectForRefine(id); setDetailId(null); }}
          onSelect={setSelectedId}
          onEdit={(id) => { setSelectedId(id); setInspectorId(id); }}
          onArchive={(id) => { handleArchiveModule(id); setDetailId(null); }}
        />
      )}

      {inspectorModule && (
        <Inspector
          module={inspectorModule}
          onCommit={commitModule}
          onClose={() => setInspectorId(null)}
          onRefine={(id) => { handleSelectForRefine(id); setInspectorId(null); }}
          onDuplicate={handleDuplicateModule}
          onArchive={handleArchiveModule}
        />
      )}

      {archivedOpen && (
        <ArchivedPanel
          items={archived}
          onClose={() => setArchivedOpen(false)}
          onRestore={handleRestoreModule}
          onDelete={handleDeleteArchived}
        />
      )}

      {snapshotsOpen && (
        <SnapshotsPanel
          snapshots={snapshots}
          pageName={activePage?.name ?? "this page"}
          onClose={() => setSnapshotsOpen(false)}
          onSave={handleSaveSnapshot}
          onRestore={handleRestoreSnapshot}
          onDelete={handleDeleteSnapshot}
        />
      )}
      </main>

      <CommandPalette
        open={cmdOpen}
        onClose={() => setCmdOpen(false)}
        pages={pages}
        allModules={allModules}
        actions={actions}
        onGoToPage={handleGoToPage}
        onGoToModule={handleGoToModule}
      />
      <ShortcutsModal open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
      <ConfirmDialog
        open={pageDeleteConfirm !== null}
        title={pageDeleteConfirm
          ? `Delete "${pageDeleteConfirm.page.name}" and its ${pageDeleteConfirm.moduleIds.length} module${pageDeleteConfirm.moduleIds.length === 1 ? "" : "s"}${pageDeleteConfirm.archivedCount > 0 ? " (including archived)" : ""}?`
          : ""}
        body="This cannot be undone."
        confirmLabel="Delete"
        onConfirm={handleConfirmDeletePage}
        onCancel={handleCancelDeletePage}
      />
      {introOpen && <IntroSplash onDone={dismissIntro} />}
    </div>
  );
}
