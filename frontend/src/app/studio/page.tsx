"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type { StudioLayout, StudioUseCase } from "@/lib/types";
import { Module } from "@/components/Module";
import { Icon } from "@/components/Icon";

const NOW = new Date().toISOString();
const noop = () => {};

export default function StudioPage() {
  const [useCases, setUseCases] = useState<StudioUseCase[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [layouts, setLayouts] = useState<StudioLayout[]>([]);
  const [loadingLayouts, setLoadingLayouts] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importUrl, setImportUrl] = useState("");
  const [matchColors, setMatchColors] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const flash = (m: string) => { setToast(m); window.setTimeout(() => setToast(null), 2800); };

  const reloadUseCases = useCallback(async () => {
    try { setUseCases(await api.studioUseCases()); } catch { /* offline */ }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const uc = await api.studioUseCases();
        setUseCases(uc);
        setActive((cur) => cur ?? uc[0]?.key ?? null);
      } catch { /* backend down */ }
    })();
  }, []);

  const loadLayouts = useCallback(async (key: string) => {
    setLoadingLayouts(true);
    try { setLayouts(await api.studioLayouts(key)); }
    catch { setLayouts([]); }
    finally { setLoadingLayouts(false); }
  }, []);

  useEffect(() => { if (active) loadLayouts(active); }, [active, loadLayouts]);

  const activeUC = useCases.find((u) => u.key === active) ?? null;

  const generate = async () => {
    if (!active) return;
    setGenerating(true);
    try {
      await api.studioGenerate(active, 4);
      await loadLayouts(active);
      await reloadUseCases();
      flash("Mined 4 candidate layouts.");
    } catch {
      flash("Generation failed — is the backend running?");
    } finally {
      setGenerating(false);
    }
  };

  const doImport = async (opts: { file?: File; url?: string }) => {
    if (!active) return;
    setImporting(true);
    try {
      // Staged capture engine: full-fidelity read → faithful Trus re-skin → coverage score.
      const ly = await api.studioCapture(active, { ...opts, matchColors });
      await loadLayouts(active);
      await reloadUseCases();
      setImportUrl("");
      const conf = typeof ly.confidence === "number" ? ` · ${Math.round(ly.confidence * 100)}% match` : "";
      const seeded = (ly.capture_meta?.capture_quality as string) === "high"
        ? " — added to the generation library." : ".";
      flash(`Captured a layout from the screenshot${conf}${seeded}`);
    } catch (e) {
      const msg = e instanceof ApiError
        ? (e.refusal || (typeof e.detail === "string" ? e.detail : "Import failed"))
        : "Import failed";
      flash(msg);
    } finally {
      setImporting(false);
    }
  };

  const promote = async (id?: string) => {
    if (!id) return;
    try {
      const r = await api.studioPromote(id);
      flash(`Added to the generation library — ${r.library.entries} template${r.library.entries === 1 ? "" : "s"} now seed real-time generation.`);
    } catch { flash("Couldn't add to library."); }
  };

  const remove = async (id?: string) => {
    if (!id) return;
    await api.studioDeleteLayout(id).catch(() => {});
    setLayouts((prev) => prev.filter((l) => l.id !== id));
    reloadUseCases();
  };

  const btn = "rounded-md px-2.5 py-1 text-xs font-medium transition";

  return (
    <div className="flex h-screen w-full bg-[var(--background)] text-[var(--foreground)]">
      {/* Use-case rail */}
      <aside className="shrink-0 w-60 border-r border-[var(--border)] bg-[var(--surface)]/60 backdrop-blur flex flex-col">
        <div className="px-4 h-14 flex items-center gap-2 border-b border-[var(--border)] shrink-0">
          <span className="text-[var(--accent)]"><Icon name="grid" size={18} /></span>
          <span className="text-sm font-semibold tracking-tight">Layout Studio</span>
        </div>
        <div className="px-2 py-2 text-[10px] uppercase tracking-wide text-[var(--muted)]">Use cases</div>
        <nav className="flex-1 overflow-y-auto px-2 pb-3 flex flex-col gap-0.5">
          {useCases.map((u) => (
            <button
              key={u.key}
              type="button"
              onClick={() => setActive(u.key)}
              className={`text-left rounded-lg px-2 py-1.5 flex items-center gap-2 transition ${
                active === u.key
                  ? "bg-[var(--surface-elevated)] text-[var(--foreground)]"
                  : "text-[var(--muted)] hover:bg-[var(--surface-elevated)]/60 hover:text-[var(--foreground)]"
              }`}
            >
              <span className="shrink-0" style={{ color: active === u.key ? "var(--accent)" : undefined }}>
                <Icon name={u.icon ?? "grid"} size={15} />
              </span>
              <span className="flex-1 min-w-0 truncate text-sm">{u.title}</span>
              {u.count > 0 && (
                <span className="shrink-0 text-[10px] rounded-full bg-[var(--surface)] border border-[var(--border)] px-1.5 leading-tight text-[var(--muted)]">{u.count}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="p-2 border-t border-[var(--border)]">
          <Link href="/" className="w-full flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--surface-elevated)] transition">
            <Icon name="chevronLeft" size={16} /> Back to canvas
          </Link>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 min-w-0 flex flex-col">
        <header className="h-14 shrink-0 px-5 flex items-center gap-3 border-b border-[var(--border)] bg-[var(--background)]/85 backdrop-blur">
          <div className="min-w-0">
            <div className="text-sm font-semibold tracking-tight truncate">
              {activeUC ? activeUC.title : "Layout Studio"}
            </div>
            <div className="text-xs text-[var(--muted)] truncate">
              {activeUC
                ? `Layouts modelled after ${activeUC.apps.slice(0, 4).join(", ")}${activeUC.apps.length > 4 ? "…" : ""}`
                : "A library of layout patterns per use case — to seed real-time generation"}
            </div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <input ref={fileRef} type="file" accept="image/*" className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) doImport({ file: f }); e.currentTarget.value = ""; }} />
            <button
              type="button"
              onClick={() => setMatchColors((v) => !v)}
              disabled={importing || !active}
              title="Carry the source app's accent colour into the imported layout (off = Trus brand look)"
              aria-pressed={matchColors}
              className={`${btn} press border flex items-center gap-1.5 disabled:opacity-40 ${
                matchColors
                  ? "border-[var(--accent)] text-[var(--accent)]"
                  : "border-[var(--border)] text-[var(--muted)] hover:text-[var(--foreground)]"
              }`}
            >
              <Icon name={matchColors ? "check" : "sparkles"} size={14} />
              Match colors
            </button>
            <input
              value={importUrl}
              onChange={(e) => setImportUrl(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && importUrl.trim()) doImport({ url: importUrl.trim() }); }}
              placeholder="image URL ↵"
              disabled={importing || !active}
              aria-label="Import a layout from an image URL"
              className="w-36 rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-[var(--accent)]/50 disabled:opacity-40"
            />
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={importing || !active}
              title="Import a reference screenshot — a vision model turns it into a layout"
              className={`${btn} press border border-[var(--border)] text-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-40 flex items-center gap-1.5`}
            >
              <Icon name="camera" size={14} />
              {importing ? "Reading…" : "Import screenshot"}
            </button>
            <button
              type="button"
              onClick={generate}
              disabled={generating || !active}
              className={`${btn} bg-[var(--accent)] text-[var(--accent-fg)] hover:brightness-110 active:scale-95 disabled:opacity-40 flex items-center gap-1.5`}
            >
              <Icon name="sparkles" size={14} className={generating ? "animate-pulse" : ""} />
              {generating ? "Mining…" : "Generate layouts"}
            </button>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-5">
          {!active ? (
            <p className="text-sm text-[var(--muted)]">Loading use cases… make sure the backend is running on :8000.</p>
          ) : layouts.length === 0 ? (
            <div className="grid place-items-center h-full text-center">
              <div className="max-w-md flex flex-col items-center gap-3">
                <span className="text-[var(--accent)]"><Icon name={activeUC?.icon ?? "grid"} size={28} /></span>
                <h2 className="text-lg font-semibold">No layouts yet for {activeUC?.title}</h2>
                <p className="text-sm text-[var(--muted)] leading-relaxed">
                  {loadingLayouts
                    ? "Loading…"
                    : `Generate candidate layouts modelled after ${activeUC?.apps.slice(0, 3).join(", ")} and others. Each one is a real Trus tool you can preview, curate, and add to the generation library.`}
                </p>
                {!loadingLayouts && (
                  <button type="button" onClick={generate} disabled={generating}
                    className={`${btn} bg-[var(--accent)] text-[var(--accent-fg)] hover:brightness-110 active:scale-95 disabled:opacity-40`}>
                    {generating ? "Mining…" : "✦ Generate layouts"}
                  </button>
                )}
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap gap-4 items-start">
              {layouts.map((ly, i) => (
                <div key={ly.id ?? i} className="w-[340px] rounded-2xl border border-[var(--border)] bg-[var(--surface)]/40 p-3 flex flex-col gap-2 animate-pop">
                  <div className="flex items-start justify-between gap-2 px-0.5">
                    <div className="min-w-0">
                      <div className="text-sm font-semibold truncate">{ly.label}</div>
                      {ly.inspired_by && (
                        <div className="text-[11px] text-[var(--muted)] truncate">inspired by {ly.inspired_by}</div>
                      )}
                    </div>
                  </div>
                  <Module
                    variant="preview"
                    module={{ id: ly.id ?? `studio-${i}`, config: ly.config, created_at: NOW, updated_at: NOW }}
                    crossModuleValues={{}}
                    selected={false}
                    onChange={noop}
                    onDelete={noop}
                    onUndo={noop}
                    onSelectForRefine={noop}
                    onSelect={noop}
                    onDragStart={noop}
                    onResizeStart={noop}
                  />
                  <div className="flex gap-2 pt-0.5">
                    <button type="button" onClick={() => promote(ly.id)}
                      className={`${btn} flex-1 border border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent)] hover:text-[var(--accent-fg)]`}>
                      + Add to library
                    </button>
                    <button type="button" onClick={() => remove(ly.id)}
                      className={`${btn} text-[var(--muted)] hover:text-[var(--danger)]`}>
                      Remove
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>

      {toast && (
        <div className="fixed bottom-5 left-1/2 -translate-x-1/2 z-30 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 py-2 text-sm shadow-lg animate-pop">
          {toast}
        </div>
      )}
    </div>
  );
}
