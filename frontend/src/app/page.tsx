"use client";

import { useCallback, useEffect, useState } from "react";
import { Canvas } from "@/components/Canvas";
import { PageBar } from "@/components/PageBar";
import { PromptBar } from "@/components/PromptBar";
import { api } from "@/lib/api";
import type { Page, StoredModule } from "@/lib/types";

export default function Home() {
  const [pages, setPages] = useState<Page[]>([]);
  const [activePageId, setActivePageId] = useState<string | null>(null);
  const [modules, setModules] = useState<StoredModule[]>([]);
  const [loading, setLoading] = useState(true);
  const [refineTarget, setRefineTarget] = useState<StoredModule | null>(null);

  // Load pages on mount, then load modules for the first page.
  useEffect(() => {
    api
      .listPages()
      .then((list) => {
        setPages(list);
        const first = list[0] ?? null;
        if (first) {
          setActivePageId(first.id);
          return api.listModules(first.id);
        }
        return Promise.resolve([] as StoredModule[]);
      })
      .then((mods) => setModules(mods))
      .catch((err) => console.error("Failed to load workspace", err))
      .finally(() => setLoading(false));
  }, []);

  // Reload modules whenever active page changes (but not on first mount).
  const [firstLoad, setFirstLoad] = useState(true);
  useEffect(() => {
    if (firstLoad) { setFirstLoad(false); return; }
    if (!activePageId) return;
    setModules([]);
    api
      .listModules(activePageId)
      .then((list) => setModules(list))
      .catch((err) => console.error("Failed to load modules for page", err));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activePageId]);

  const handleNewModule = useCallback((m: StoredModule) => {
    setModules((prev) => {
      const cascadeOffset = prev.length * 40;
      const placed: StoredModule = {
        ...m,
        config: {
          ...m.config,
          layout: {
            ...m.config.layout,
            x: m.config.layout.x + cascadeOffset,
            y: m.config.layout.y + cascadeOffset,
          },
        },
      };
      void api.patchModule(placed.id, placed.config).catch(() => {});
      return [...prev, placed];
    });
  }, []);

  const handleModuleChange = useCallback((updated: StoredModule) => {
    setModules((prev) => prev.map((m) => (m.id === updated.id ? updated : m)));
  }, []);

  const handleDeleteModule = useCallback((id: string) => {
    setModules((prev) => prev.filter((m) => m.id !== id));
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

  const handleRefinedModule = useCallback((updated: StoredModule) => {
    setModules((prev) => prev.map((m) => (m.id === updated.id ? updated : m)));
    setRefineTarget(null);
  }, []);

  // Page handlers
  const handleSelectPage = useCallback((id: string) => {
    setActivePageId(id);
    setRefineTarget(null);
  }, []);

  const handlePageCreated = useCallback((page: Page) => {
    setPages((prev) => [...prev, page]);
    setActivePageId(page.id);
    setModules([]);
    setRefineTarget(null);
  }, []);

  const handlePageRenamed = useCallback((page: Page) => {
    setPages((prev) => prev.map((p) => (p.id === page.id ? page : p)));
  }, []);

  const handlePageDeleted = useCallback(
    (id: string) => {
      setPages((prev) => {
        const remaining = prev.filter((p) => p.id !== id);
        const newActive = remaining[remaining.length - 1]?.id ?? null;
        setActivePageId(newActive);
        return remaining;
      });
    },
    [],
  );

  const activeModules = modules.filter((m) => !m.page_id || m.page_id === activePageId);

  return (
    <main className="flex-1 flex flex-col h-screen relative">
      <header className="absolute top-0 left-0 right-0 z-10 flex items-center justify-between px-6 py-4 pointer-events-none">
        <div className="pointer-events-auto">
          <h1 className="text-xl font-semibold tracking-tight">Trus</h1>
          <p className="text-xs text-[var(--muted)] -mt-0.5">
            {loading
              ? "Loading…"
              : activeModules.length === 0
                ? "An empty canvas. Tell it what you want to organize."
                : `${activeModules.length} module${activeModules.length === 1 ? "" : "s"}`}
          </p>
        </div>
      </header>

      {pages.length > 0 && activePageId && (
        <PageBar
          pages={pages}
          activePageId={activePageId}
          onSelectPage={handleSelectPage}
          onPageCreated={handlePageCreated}
          onPageRenamed={handlePageRenamed}
          onPageDeleted={handlePageDeleted}
        />
      )}

      <Canvas
        modules={activeModules}
        activePageId={activePageId ?? undefined}
        onModuleChange={handleModuleChange}
        onModuleDelete={handleDeleteModule}
        onModuleUndo={handleUndoModule}
        onModuleSelectForRefine={handleSelectForRefine}
        onNewModule={handleNewModule}
      />
      <PromptBar
        onModule={handleNewModule}
        activePageId={activePageId ?? undefined}
        refineTarget={refineTarget}
        onRefineModule={handleRefinedModule}
        onClearRefine={handleClearRefine}
      />
    </main>
  );
}
