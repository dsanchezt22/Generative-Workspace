"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { Canvas } from "@/components/Canvas";
import { ConversationPanel } from "@/components/ConversationPanel";
import { ArchivedPanel } from "@/components/ArchivedPanel";
import { SnapshotsPanel } from "@/components/SnapshotsPanel";
import { ProfilePanel } from "@/components/ProfilePanel";
import { SharePanel } from "@/components/SharePanel";
import { ActivityPanel } from "@/components/ActivityPanel";
import { ApprovalBadge } from "@/components/ApprovalBadge";
import { AppFrame } from "@/components/AppFrame";
import { Inspector } from "@/components/Inspector";
import { DetailView } from "@/components/DetailView";
import { Sidebar } from "@/components/Sidebar";
import { PromptBar } from "@/components/PromptBar";
import { AppearanceMenu } from "@/components/AppearanceMenu";
import { EmptyState } from "@/components/EmptyState";
import { CommandPalette, type Action } from "@/components/CommandPalette";
import { ShortcutsModal } from "@/components/ShortcutsModal";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { EntryScreen } from "@/components/EntryScreen";
import { InviteGate } from "@/components/InviteGate";
import { Icon } from "@/components/Icon";
import { api, ApiError } from "@/lib/api";
import { createModuleSaver, type SaveStatus } from "@/lib/moduleSaver";
import { serverViewOf, type ViewState } from "@/lib/viewPersist";
import { useAppearance } from "@/lib/appearance";
import { resolveIconName } from "@/lib/theme";
import type { CommitModule, InsertStructureResponse, Message, ModuleConfig, Page, PageOverview, Snapshot, StoredModule } from "@/lib/types";

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
  // R-502: live module count per page, for the child-page portal tiles' cheap
  // "N tools" preview. One grouped COUNT server-side — never loads child configs.
  // V2 SURF: one grouped overview per page (modules/agents/last run), keyed by
  // page id — feeds the portal tiles + AppFrame. `now` is refreshed alongside so
  // the tiles' relative "agent ran …" stays fresh without impurity in render.
  const [overviews, setOverviews] = useState<Record<string, PageOverview>>({});
  const [now, setNow] = useState(() => Date.now());
  // V2 SURF §6: bumped on "back" — Canvas seeds the reverse zoom from this child.
  const [portalReturnReq, setPortalReturnReq] = useState<{ childId: string; n: number } | undefined>(undefined);
  // R-221-223 unification: a snapped sketch's proposed tools, in flight from
  // Canvas to the PromptBar's preview→confirm stack. `n` distinguishes re-snaps.
  const [sketchPreviews, setSketchPreviews] = useState<{
    configs: ModuleConfig[];
    plan: string | null;
    n: number;
  } | null>(null);
  // R-801: the "remembers you" profile surface. ProfilePanel fetches + owns its
  // own facts state; page.tsx only toggles visibility and keeps it mutually
  // exclusive with the other right-hand panels.
  const [profileOpen, setProfileOpen] = useState(false);
  // V2 Pulse: the "what happened / what needs your tap" surface. Joins the
  // mutually-exclusive right-aside set. `pendingCount` drives the home badge +
  // the header toggle's count dot — polled cheaply (approvalCount), refreshed on
  // focus and after any panel mutation.
  const [activityOpen, setActivityOpen] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);
  // Per-surface sharing (SHARE-1..3). `shareOpen` toggles the SharePanel (joins
  // the mutually-exclusive right-aside set); `shareActive` drives the always-
  // visible header pip — refreshed on page change and lifted from the panel.
  const [shareOpen, setShareOpen] = useState(false);
  const [shareActive, setShareActive] = useState(false);
  // R-1102: page delete is the most destructive action (cascades every module
  // on the page) — always confirmed, stating the module count. Holds the page
  // plus its real module ids: `modules` state only covers the ACTIVE page,
  // but any sidebar row can be deleted, so the ids are fetched per-page.
  const [pageDeleteConfirm, setPageDeleteConfirm] = useState<{ page: Page; moduleIds: string[]; archivedCount: number } | null>(null);
  // R-1306: keyboard Delete on a focused module asks first (ConfirmDialog) —
  // a key press is easier to fat-finger than the card's ✕ button. On confirm,
  // focus moves to the canvas <main> (the card is gone), never lost to <body>.
  const [archiveConfirm, setArchiveConfirm] = useState<StoredModule | null>(null);
  const mainRef = useRef<HTMLElement | null>(null);
  const [cmdOpen, setCmdOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [allModules, setAllModules] = useState<StoredModule[]>([]);
  const [focusReq, setFocusReq] = useState<{ id: string; n: number } | undefined>(undefined);
  const [fitReq, setFitReq] = useState(0);
  const [promptFocus, setPromptFocus] = useState(0);
  // R-101: the entry-as-interview front door. `introOpen` shows it; `entrySubmit`
  // carries a collected prompt to PromptBar's auto-submit (handoff to the normal
  // preview flow). `introDecidedRef` pins the first-load visibility decision so a
  // later empty canvas (e.g. archiving everything) can't re-trigger it.
  const [introOpen, setIntroOpen] = useState(false);
  const [entrySubmit, setEntrySubmit] = useState<string | null>(null);
  const introDecidedRef = useRef(false);
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

  // Decide the entry-screen once, after the first data load settles: show it on
  // a session's FIRST visit AND only when the workspace is empty. A returning
  // user with content (or a freshly seeded starter) lands straight on their
  // canvas (R-101). Deferred past `loading` so we know whether modules exist.
  useEffect(() => {
    if (loading || introDecidedRef.current) return;
    introDecidedRef.current = true;
    const firstVisit = !sessionStorage.getItem("trus-intro-seen");
    // `modules` holds the active page's modules once loaded (seeded starters
    // included), so an empty length here means a genuinely empty workspace.
    if (firstVisit && modules.length === 0) setIntroOpen(true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading]);

  const closeEntry = useCallback(() => {
    setIntroOpen(false);
    sessionStorage.setItem("trus-intro-seen", "1");
  }, []);
  // Skip / Escape: dismiss to the canvas and focus the creation bar.
  const handleEntrySkip = useCallback(() => {
    closeEntry();
    setPromptFocus((n) => n + 1);
  }, [closeEntry]);
  // R-101: the entry collected a prompt — hand it to PromptBar to auto-submit
  // (produces a preview exactly like a typed prompt) and dissolve to the canvas.
  const handleEntrySubmit = useCallback((prompt: string) => {
    closeEntry();
    setEntrySubmit(prompt);
  }, [closeEntry]);
  // R-105: re-open the entry mid-session from the EmptyState.
  const handleStartConversation = useCallback(() => setIntroOpen(true), []);

  useEffect(() => {
    const isNarrow = typeof window !== "undefined" && window.innerWidth < 640;
    // R-1304: below Tailwind `sm` the 224px expanded sidebar squeezes the canvas
    // to a sliver AND pushes the header past the viewport (a real horizontal page
    // scroll). Always start collapsed on a narrow viewport, overriding even a
    // stored (desktop) expand preference — the contract is "the sidebar collapses
    // rather than squeezing the canvas to nothing." Desktop keeps honoring the
    // stored choice unchanged.
    if (isNarrow) {
      setSidebarCollapsed(true);
    } else {
      const stored = localStorage.getItem("trus-sidebar-collapsed");
      if (stored !== null) setSidebarCollapsed(stored === "1");
    }
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

  // V2 SURF: refresh the per-page overviews for the portal tiles + AppFrame. One
  // grouped owner-scoped query; re-fetched on navigation and after generation.
  // Fetch failure leaves tiles rendering name+icon only — never fabricated data.
  const refreshOverview = useCallback(() => {
    api.pagesOverview().then((o) => { setOverviews(o); setNow(Date.now()); }).catch(() => {});
  }, []);

  // V2 Pulse: the badge's freshness. One indexed COUNT (approvalCount) — cheap
  // enough to poll. Swallow failures (e.g. the endpoint not yet reachable): the
  // badge simply stays at its last known value rather than surfacing an error.
  const refreshPendingCount = useCallback(() => {
    api.approvalCount().then((r) => setPendingCount(r.pending)).catch(() => {});
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
        } else if (
          // R-502 discoverability: portal tiles live in a shelf ABOVE the module
          // grid, so a raw {0,0,1} view leaves them above the viewport. On the
          // FIRST visit of a page that has child portals (no saved view yet —
          // neither local nor server-side, R-504), defer a fit so modules + the
          // portal shelf land framed together. A page the user has already
          // arranged keeps its saved view (no regression).
          pages.some((p) => (p.parent_id ?? null) === activePageId) &&
          !localStorage.getItem(`trus-view-${activePageId}`) &&
          serverViewOf(pages.find((p) => p.id === activePageId)) === null
        ) {
          window.setTimeout(() => setFitReq((n) => n + 1), 180);
        }
      })
      .catch((err) => console.error("Failed to load modules for page", err));
    reloadConvo(activePageId);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activePageId]);

  // R-502: keep the portal tiles' "N tools" counts fresh — refetch when the
  // active page changes (incl. first load once activePageId resolves, and when
  // returning to a parent after building in a child).
  useEffect(() => {
    if (!activePageId) return;
    refreshOverview();
  }, [activePageId, refreshOverview]);

  // V2 Pulse: poll the pending-approval count every 30s (the freshness ceiling
  // for the home badge), skipping while the tab is hidden, plus an immediate
  // refresh on window focus. Not started until the session is claimed (the gate
  // has no owner to count for). Cleared on unmount.
  useEffect(() => {
    if (gated) return;
    refreshPendingCount();
    const onFocus = () => refreshPendingCount();
    window.addEventListener("focus", onFocus);
    const iv = window.setInterval(() => {
      if (!document.hidden) refreshPendingCount();
    }, 30000);
    return () => {
      window.removeEventListener("focus", onFocus);
      window.clearInterval(iv);
    };
  }, [gated, refreshPendingCount]);

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
    setProfileOpen(false);
    setActivityOpen(false);
    setShareOpen(false);
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

  // V2 SURF §6: leaving an app (AppFrame back / breadcrumb) switches to the parent
  // AND bumps portalReturnReq in the same commit — Canvas plays the reverse zoom
  // (seed inside the child's tile → animate out to the parent's saved view).
  const handleBack = useCallback((childId: string, parentId: string) => {
    setActivePageId(parentId);
    setRefineTarget(null);
    setPortalReturnReq((p) => ({ childId, n: (p?.n ?? 0) + 1 }));
  }, []);

  // V2 SURF (ONB-1): a confirmed structure landed real pages/modules/automations.
  // Merge the returned pages (they surface as portal tiles), refresh the overview,
  // frame the new shelf, and honestly report anything the server had to drop.
  const handleStructureConfirmed = useCallback((res: InsertStructureResponse) => {
    setPages((prev) => {
      const byId = new Map(prev.map((p) => [p.id, p]));
      for (const p of res.pages) byId.set(p.id, p);
      return Array.from(byId.values());
    });
    refreshOverview();
    window.setTimeout(() => setFitReq((n) => n + 1), 160);
    if (res.dropped.length > 0) {
      flashNotice(
        `Couldn't build ${res.dropped.length} item${res.dropped.length === 1 ? "" : "s"}: ${res.dropped.join(", ")}.`,
      );
    }
  }, [refreshOverview, flashNotice]);

  // R-504: dragging a child's portal tile persists its placement on the page row
  // (owner-scoped server-side). Optimistic — the tile stays where the user dropped
  // it while the PATCH lands; on failure it rolls back to the prior spot (the move
  // never persisted, so leaving it would silently revert on next load) and flashes
  // a low-drama notice.
  const handlePortalMove = useCallback(async (pageId: string, x: number, y: number) => {
    let prevPos: { portal_x?: number | null; portal_y?: number | null } | undefined;
    setPages((prev) =>
      prev.map((p) => {
        if (p.id !== pageId) return p;
        prevPos = { portal_x: p.portal_x, portal_y: p.portal_y };
        return { ...p, portal_x: x, portal_y: y };
      }),
    );
    try {
      await api.updatePage(pageId, { portal_x: x, portal_y: y });
    } catch (err) {
      console.error("Failed to persist portal position", err);
      if (prevPos) {
        const restore = prevPos;
        setPages((prev) => prev.map((p) => (p.id === pageId ? { ...p, ...restore } : p)));
      }
      flashNotice("Couldn't save the tile's new spot — moved it back.");
    }
  }, [flashNotice]);

  // R-504 completion: Canvas's debounced view save → persist this page's pan/zoom
  // on its row (owner-scoped server-side) so the view resumes on another device.
  // localStorage (written by Canvas on the same tick) stays the instant offline
  // fallback, so a failed PATCH is logged, never surfaced — the local view holds.
  // `pages` is refreshed in place so returning to this page mid-session reloads
  // the view just saved, not the stale value fetched at startup.
  const handleViewSave = useCallback(async (pageId: string, v: ViewState) => {
    try {
      await api.updatePage(pageId, { view_x: v.x, view_y: v.y, view_zoom: v.zoom });
      setPages((prev) =>
        prev.map((p) => (p.id === pageId ? { ...p, view_x: v.x, view_y: v.y, view_zoom: v.zoom } : p)),
      );
    } catch (err) {
      console.error("Failed to persist page viewport", err);
    }
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
      // R-503: mirror the server's reparent-not-orphan — the deleted page's
      // direct children move up to its own parent (grandparent, or root), so the
      // sidebar tree stays correct without a reload instead of orphaning them.
      const grandparent = req.page.parent_id ?? null;
      const remaining = prev
        .filter((p) => p.id !== req.page.id)
        .map((p) => ((p.parent_id ?? null) === req.page.id ? { ...p, parent_id: grandparent } : p));
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

  // R-1306: keyboard-initiated archive — open the confirm, don't act yet.
  const handleRequestArchive = useCallback((id: string) => {
    const m = modulesRef.current.find((x) => x.id === id);
    if (m) setArchiveConfirm(m);
  }, []);

  const handleConfirmArchive = useCallback(() => {
    const m = archiveConfirm;
    setArchiveConfirm(null);
    if (!m) return;
    handleArchiveModule(m.id);
    // The focused card is gone, so ConfirmDialog's restore-to-opener finds a
    // disconnected node and skips — land focus on the canvas <main> instead
    // (after React commits the dialog's cleanup, hence the timeout).
    window.setTimeout(() => mainRef.current?.focus(), 0);
  }, [archiveConfirm, handleArchiveModule]);

  const openArchived = useCallback(async () => {
    setSelectedId(null);
    setInspectorId(null);
    setConvoOpen(false);
    setSnapshotsOpen(false);
    setProfileOpen(false);
    setActivityOpen(false);
    setShareOpen(false);
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
    setProfileOpen(false);
    setActivityOpen(false);
    setShareOpen(false);
    try { setSnapshots(await api.listSnapshots(activePageId)); } catch { setSnapshots([]); }
    setSnapshotsOpen(true);
  }, [activePageId]);

  // Profile opens like the others (mutually exclusive with the right-hand
  // panels). The panel fetches its own facts on mount, so this just toggles it.
  const openProfile = useCallback(() => {
    setSelectedId(null);
    setInspectorId(null);
    setConvoOpen(false);
    setArchivedOpen(false);
    setSnapshotsOpen(false);
    setActivityOpen(false);
    setShareOpen(false);
    setProfileOpen(true);
  }, []);

  // V2 Pulse opens like the other right-hand panels (mutually exclusive). It
  // fetches its own lists on mount, so this just clears selection/inspector and
  // closes the siblings. On close we re-poll the count so a just-approved item
  // updates the badge immediately.
  const openActivity = useCallback(() => {
    setSelectedId(null);
    setInspectorId(null);
    setConvoOpen(false);
    setArchivedOpen(false);
    setSnapshotsOpen(false);
    setProfileOpen(false);
    setShareOpen(false);
    setActivityOpen(true);
  }, []);

  // Share opens like the other right-hand panels (mutually exclusive). The panel
  // fetches its own status on mount, so this just clears selection and closes the
  // siblings.
  const openShare = useCallback(() => {
    setSelectedId(null);
    setInspectorId(null);
    setConvoOpen(false);
    setArchivedOpen(false);
    setSnapshotsOpen(false);
    setProfileOpen(false);
    setActivityOpen(false);
    setShareOpen(true);
  }, []);

  // SHARE-2: the always-visible share state. Re-check on every page change (and
  // on first resolve); the panel lifts subsequent changes via onStateChange so
  // the pip stays in sync without a re-fetch. A pre-share page or unreachable
  // endpoint reads as not-shared.
  useEffect(() => {
    if (!activePageId) { setShareActive(false); return; }
    api.shareStatus(activePageId).then((s) => setShareActive(s.active)).catch(() => setShareActive(false));
  }, [activePageId]);

  // A journal deep-link was tapped: close Pulse and go to what the automation
  // touched — focus the module if it's on this page, else switch to its page
  // (the module is focused once that page's modules load, the existing
  // pendingFocusRef idiom), or just switch pages when only a page is named.
  const handlePulseNavigate = useCallback((t: { moduleId?: string | null; pageId?: string | null }) => {
    setActivityOpen(false);
    if (t.moduleId) {
      const onActive = modulesRef.current.some((m) => m.id === t.moduleId);
      if (onActive) {
        setSelectedId(t.moduleId);
        setFocusReq({ id: t.moduleId, n: Date.now() });
      } else if (t.pageId) {
        pendingFocusRef.current = t.moduleId;
        setActivePageId(t.pageId);
      } else {
        setSelectedId(t.moduleId);
        setFocusReq({ id: t.moduleId, n: Date.now() });
      }
    } else if (t.pageId) {
      setActivePageId(t.pageId);
    }
  }, []);

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
    setActivityOpen(false);
    setShareOpen(false);
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
      if (e.key === "Escape") { setCmdOpen(false); setShortcutsOpen(false); setArchivedOpen(false); setSnapshotsOpen(false); setProfileOpen(false); setActivityOpen(false); setShareOpen(false); setDetailId(null); setSelectedId(null); setInspectorId(null); setConvoOpen(false); return; }
      if (!typing && !mod) {
        if (e.key === "?" || (e.shiftKey && e.key === "/")) setShortcutsOpen(true);
        else if (e.key.toLowerCase() === "f") setFitReq((n) => n + 1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedId, toggleSidebar, handleDuplicateModule, handleUndoModule]);

  const activeModules = modules.filter((m) => !m.page_id || m.page_id === activePageId);
  // R-502: this page's direct children render as enterable portal tiles on its canvas.
  const childPages = useMemo(
    () => pages.filter((p) => (p.parent_id ?? null) === (activePageId ?? null)),
    [pages, activePageId],
  );
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
      {/* R-1306: the page's FIRST tabbable — jumps a keyboard user straight to
          the canvas instead of forcing a tour of the sidebar. Visually hidden
          until focused, then a small on-theme chip (existing tokens only). */}
      <a
        href="#canvas-main"
        onClick={(e) => { e.preventDefault(); mainRef.current?.focus(); }}
        className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-[70] focus:rounded-md focus:border focus:border-[var(--accent)] focus:bg-[var(--surface)] focus:px-3 focus:py-1.5 focus:text-sm"
      >
        Skip to canvas
      </a>
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
        onOpenProfile={openProfile}
      />
      {/* R-1306: the canvas landmark. tabIndex={-1} makes it a programmatic
          focus target (skip link, post-archive focus) without joining Tab order;
          outline-none because landing here is a hand-off, not a highlight. */}
      <main
        ref={mainRef}
        id="canvas-main"
        tabIndex={-1}
        aria-label="Canvas"
        className="flex-1 flex flex-col relative min-w-0 focus:outline-none"
      >
      {/* R-1304: tighter gap/padding below `sm` so the icon-only header row
          (labels are `hidden sm:inline`) fits a 375px phone without forcing a
          horizontal PAGE scroll; desktop keeps gap-3 / px-5. */}
      <header className="absolute top-0 inset-x-0 z-20 h-14 px-2 sm:px-5 flex items-center gap-1.5 sm:gap-3 border-b border-[var(--border)] bg-[var(--background)]/85 backdrop-blur">
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
          {activePageId && (
            <button
              type="button"
              onClick={() => (shareOpen ? setShareOpen(false) : openShare())}
              className={`shrink-0 ml-1 flex items-center justify-center w-6 h-6 rounded-md border transition ${
                shareOpen
                  ? "border-[var(--accent)] text-[var(--foreground)]"
                  : "border-transparent text-[var(--muted)] hover:text-[var(--foreground)]"
              }`}
              title="Share this surface (read-only link)"
              aria-label="Share this surface"
            >
              <Icon name="link" size={14} />
            </button>
          )}
          {/* SHARE-2: always-visible state — muted mono, never the magenta accent. */}
          {shareActive && (
            <span
              className="shrink-0 text-[10px] font-mono uppercase tracking-wide text-[var(--muted)] rounded border border-[var(--border)] px-1.5 py-0.5"
              title="A read-only share link is active"
            >
              Shared
            </span>
          )}
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
          onClick={() => setConvoOpen((v) => { const n = !v; if (n) { setSelectedId(null); setInspectorId(null); setArchivedOpen(false); setSnapshotsOpen(false); setProfileOpen(false); setActivityOpen(false); setShareOpen(false); } return n; })}
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

        {/* V2 Pulse toggle — the always-available entry to what happened / what
            needs your tap. Chrome, so it stays muted (the magenta accent is the
            home badge); its count dot mirrors the pending total like History's. */}
        <button
          type="button"
          onClick={() => (activityOpen ? setActivityOpen(false) : openActivity())}
          className={`shrink-0 flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs transition ${
            activityOpen
              ? "border-[var(--accent)] text-[var(--foreground)]"
              : "border-[var(--border)] text-[var(--muted)] hover:text-[var(--foreground)]"
          }`}
          title="Pulse — what happened and what needs your tap"
          aria-label="Toggle Pulse"
        >
          <Icon name="activity" size={14} />
          <span className="hidden sm:inline">Pulse</span>
          {pendingCount > 0 && (
            <span className="rounded-full bg-[var(--surface-elevated)] text-[var(--muted)] px-1.5 leading-tight">
              {pendingCount}
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

      {/* V2 SURF §7: the in-app frame — shown ONLY inside a child page (an "app"),
          giving it a back affordance + identity + live status. Root canvas is
          untouched. */}
      {activePage?.parent_id && (() => {
        const parent = pages.find((p) => p.id === activePage.parent_id);
        if (!parent) return null;
        return (
          <AppFrame
            page={activePage}
            parent={parent}
            overview={overviews[activePage.id]}
            now={now}
            onBack={() => handleBack(activePage.id, parent.id)}
          />
        );
      })()}

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
        onModuleSelect={(id) => { setSelectedId(id); setInspectorId(null); if (id) { setConvoOpen(false); setArchivedOpen(false); setSnapshotsOpen(false); setProfileOpen(false); setActivityOpen(false); setShareOpen(false); } }}
        onModuleEdit={(id) => { setSelectedId(id); setInspectorId(id); setConvoOpen(false); setArchivedOpen(false); setSnapshotsOpen(false); setProfileOpen(false); setActivityOpen(false); setShareOpen(false); }}
        onModuleExpand={handleExpand}
        onModuleChange={handleModuleChange}
        onModuleCommit={commitModule}
        onModuleArchive={handleArchiveModule}
        onModuleArchiveRequest={handleRequestArchive}
        onModuleUndo={handleUndoModule}
        onModuleSelectForRefine={handleSelectForRefine}
        focusRequest={focusReq}
        fitRequest={fitReq}
        onSketchPreviews={(configs, plan) => setSketchPreviews({ configs, plan, n: Date.now() })}
        childPages={childPages}
        childOverviews={overviews}
        now={now}
        onEnterPortal={handleSelectPage}
        onPortalMove={handlePortalMove}
        portalReturnReq={portalReturnReq}
        serverView={serverViewOf(pages.find((p) => p.id === activePageId))}
        onViewSave={handleViewSave}
      />

      {!loading && activeModules.length === 0 && (
        <EmptyState onPick={handlePickChip} onStartConversation={handleStartConversation} />
      )}

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
        autoPrompt={entrySubmit}
        onAutoPromptConsumed={() => setEntrySubmit(null)}
        sketchPreviews={sketchPreviews}
        onSketchPreviewsConsumed={() => setSketchPreviews(null)}
        onStructureConfirmed={handleStructureConfirmed}
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

      {profileOpen && <ProfilePanel onClose={() => setProfileOpen(false)} />}

      {shareOpen && activePageId && (
        <SharePanel
          pageId={activePageId}
          onClose={() => setShareOpen(false)}
          onStateChange={setShareActive}
        />
      )}

      {activityOpen && (
        <ActivityPanel
          onClose={() => { setActivityOpen(false); refreshPendingCount(); }}
          onNavigate={handlePulseNavigate}
          onMutated={refreshPendingCount}
        />
      )}

      {/* The can't-miss home indicator — the home screen's single magenta
          accent, absent at 0. Hidden while Pulse is open: the panel's own
          Approve button is the one magenta action on screen at that point
          (one-accent-per-screen, not one-accent-ever). */}
      {!activityOpen && <ApprovalBadge count={pendingCount} onOpen={openActivity} />}
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
      {/* R-1306: keyboard Delete → confirm → archive (undoable, never a raw delete). */}
      <ConfirmDialog
        open={archiveConfirm !== null}
        title={`Archive "${archiveConfirm?.config.title ?? ""}"?`}
        body="It leaves the canvas but stays restorable from Archived."
        confirmLabel="Archive"
        onConfirm={handleConfirmArchive}
        onCancel={() => setArchiveConfirm(null)}
      />
      {introOpen && <EntryScreen onSubmit={handleEntrySubmit} onSkip={handleEntrySkip} />}
    </div>
  );
}
