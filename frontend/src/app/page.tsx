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
import { IntroSplash } from "@/components/IntroSplash";
import { Icon } from "@/components/Icon";
import { api, ApiError } from "@/lib/api";
import { useAppearance } from "@/lib/appearance";
import { resolveIconName } from "@/lib/theme";
import type { Message, Page, Snapshot, StoredModule } from "@/lib/types";

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
  const [generating, setGenerating] = useState(false);
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
  const [cmdOpen, setCmdOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [allModules, setAllModules] = useState<StoredModule[]>([]);
  const [focusReq, setFocusReq] = useState<{ id: string; n: number } | undefined>(undefined);
  const [fitReq, setFitReq] = useState(0);
  const [promptFocus, setPromptFocus] = useState(0);
  const [introOpen, setIntroOpen] = useState(false);
  const pendingFocusRef = useRef<string | null>(null);
  const { theme, setTheme } = useAppearance();

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

  // Load pages on mount, then load modules + conversation for the first page.
  useEffect(() => {
    let firstId: string | null = null;
    api
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
      .catch((err) => console.error("Failed to load workspace", err))
      .finally(() => setLoading(false));
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
      void api.patchModule(placed.id, placed.config).catch(() => {});
      return [...prev, placed];
    });
    reloadConvo(activePageId);
    setShowWelcome(false);
    // Frame the freshly-generated tool(s) — auto zoom/pan to fit. Deferred so the
    // content-sized card has mounted and reported its real height first.
    window.setTimeout(() => setFitReq((n) => n + 1), 160);
  }, [activePageId, reloadConvo]);

  const handleModuleChange = useCallback((updated: StoredModule) => {
    setModules((prev) => prev.map((m) => (m.id === updated.id ? updated : m)));
  }, []);

  const handleDeleteModule = useCallback((id: string) => {
    setModules((prev) => prev.filter((m) => m.id !== id));
    setSelectedId((cur) => (cur === id ? null : cur));
    setInspectorId((cur) => (cur === id ? null : cur));
    void api.deleteModule(id).catch((err) => console.error("Failed to delete module", err));
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

  const handleDeletePage = useCallback(async (id: string) => {
    try {
      await api.deletePage(id);
    } catch {
      return; // last page (409) or not found
    }
    setPages((prev) => {
      const remaining = prev.filter((p) => p.id !== id);
      setActivePageId((cur) => (cur === id ? remaining[remaining.length - 1]?.id ?? null : cur));
      return remaining;
    });
  }, []);

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
    setModules((prev) => prev.filter((m) => m.id !== id));
    setSelectedId((cur) => (cur === id ? null : cur));
    setInspectorId((cur) => (cur === id ? null : cur));
    try { await api.archiveModule(id); } catch (err) { console.error("Failed to archive", err); }
  }, []);

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
    } catch (err) { console.error("Failed to restore snapshot", err); }
  }, [activePageId]);

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
        onDelete={handleDeletePage}
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
          title="Layout Studio: browse layout patterns per use case"
        >
          <Icon name="grid" size={14} />
          <span className="hidden sm:inline">Studio</span>
        </Link>

        <AppearanceMenu />
      </header>

      <Canvas
        modules={activeModules}
        activePageId={activePageId ?? undefined}
        selectedId={selectedId}
        onModuleSelect={(id) => { setSelectedId(id); setInspectorId(null); if (id) { setConvoOpen(false); setArchivedOpen(false); setSnapshotsOpen(false); } }}
        onModuleEdit={(id) => { setSelectedId(id); setInspectorId(id); setConvoOpen(false); setArchivedOpen(false); setSnapshotsOpen(false); }}
        onModuleExpand={handleExpand}
        onModuleChange={handleModuleChange}
        onModuleDelete={handleDeleteModule}
        onModuleUndo={handleUndoModule}
        onModuleSelectForRefine={handleSelectForRefine}
        focusRequest={focusReq}
        fitRequest={fitReq}
        generating={generating}
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
        onGeneratingChange={setGenerating}
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
          onChange={handleModuleChange}
          onUndo={handleUndoModule}
          onRefine={(id) => { handleSelectForRefine(id); setDetailId(null); }}
          onSelect={setSelectedId}
          onEdit={(id) => { setSelectedId(id); setInspectorId(id); }}
          onDelete={(id) => { handleDeleteModule(id); setDetailId(null); }}
        />
      )}

      {inspectorModule && (
        <Inspector
          module={inspectorModule}
          onChange={handleModuleChange}
          onClose={() => setInspectorId(null)}
          onRefine={(id) => { handleSelectForRefine(id); setInspectorId(null); }}
          onDelete={(id) => { handleDeleteModule(id); }}
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
      {introOpen && <IntroSplash onDone={dismissIntro} />}
    </div>
  );
}
