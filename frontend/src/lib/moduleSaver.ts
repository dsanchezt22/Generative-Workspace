import { ApiError } from "./api";
import type { ModuleConfig, StoredModule } from "./types";

export type SaveStatus = "idle" | "saving" | "error";

interface Deps {
  patch: (id: string, config: ModuleConfig, rev?: number) => Promise<StoredModule>;
  getRev?: (id: string) => number | undefined;
  onSaved?: (m: StoredModule) => void;
  onError?: (id: string, err: unknown) => void;
  // R-602: fires when a stale write loses a rev race (409). The saver has
  // already dropped the pending edit for `id` — the caller must show the
  // returned module so the user sees the newer version before re-editing.
  onConflict?: (current: StoredModule) => void;
  // R-602 backlog: fires when a PATCH 404s — the module was deleted elsewhere.
  // The saver has already forgotten it; the caller must drop it from the UI.
  onMissing?: (id: string) => void;
  // R-1101: best-effort persistence that survives a page unload (a fetch with
  // `keepalive: true`). Used only by flushAllKeepalive; fire-and-forget.
  patchKeepalive?: (id: string, config: ModuleConfig, rev?: number) => void;
  debounceMs?: number;
}

export interface ModuleSaver {
  commit(id: string, config: ModuleConfig, delay?: number): void;
  flush(id: string): Promise<void>;
  flushAll(): Promise<void>;
  // R-1101: synchronously re-fire every not-yet-durable edit (pending AND
  // in-flight) through patchKeepalive so it outlives an unloading tab — the
  // unload cancels both debounced PATCHes and in-flight fetches.
  flushAllKeepalive(): void;
  status(): SaveStatus;
  subscribe(fn: () => void): () => void;
  forget(id: string): void; // module deleted — drop pending work
}

export function createModuleSaver(deps: Deps): ModuleSaver {
  const debounce = deps.debounceMs ?? 400;
  const pending = new Map<string, ModuleConfig>();
  const timers = new Map<string, ReturnType<typeof setTimeout>>();
  const inFlight = new Set<string>();
  // The config each in-flight PATCH is carrying — so flushAllKeepalive can
  // re-fire a save whose normal fetch the unload is about to abort.
  const inFlightConfigs = new Map<string, ModuleConfig>();
  const errored = new Set<string>();
  const listeners = new Set<() => void>();
  const retryDelay = new Map<string, number>();
  // Latest rev the SERVER told us (save response or 409 conflict body). The
  // caller's getRev reads React state, which syncs a render behind — a
  // follow-up flush at setTimeout(0) would resend a stale rev and 409 against
  // our own previous save. Server-known rev always wins over getRev.
  const knownRevs = new Map<string, number>();

  const notify = () => listeners.forEach((fn) => fn());

  async function save(id: string): Promise<void> {
    const config = pending.get(id);
    if (config === undefined || inFlight.has(id)) return;
    pending.delete(id);
    inFlight.add(id);
    inFlightConfigs.set(id, config);
    notify();
    try {
      const saved = await deps.patch(id, config, knownRevs.get(id) ?? deps.getRev?.(id));
      knownRevs.set(id, saved.rev);
      errored.delete(id);
      retryDelay.delete(id);
      deps.onSaved?.(saved);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.conflict) {
        // R-602: another tab won the race. Drop the pending edit (including
        // any newer one made while this stale PATCH was in flight) and any
        // scheduled retry — the user must see the latest version before
        // re-editing, never a silent overwrite or an endless retry loop.
        const t = timers.get(id);
        if (t) { clearTimeout(t); timers.delete(id); }
        pending.delete(id);
        errored.delete(id);
        retryDelay.delete(id);
        knownRevs.set(id, err.conflict.rev); // learn the winner's rev for the next edit
        deps.onConflict?.(err.conflict);
      } else if (err instanceof ApiError && err.status === 404) {
        // The module was deleted elsewhere (another tab, or server GC). There's
        // no row to save to — forget every trace of it and tell the caller to
        // drop it from the UI. Never retry: the URL will 404 forever.
        const t = timers.get(id);
        if (t) { clearTimeout(t); timers.delete(id); }
        pending.delete(id);
        errored.delete(id);
        retryDelay.delete(id);
        knownRevs.delete(id);
        deps.onMissing?.(id);
      } else {
        // keep the newest config: an edit made during the failed save wins
        if (!pending.has(id)) pending.set(id, config);
        errored.add(id);
        deps.onError?.(id, err);
        const delay = Math.min(retryDelay.get(id) ?? 1000, 30_000);
        retryDelay.set(id, delay * 2);
        schedule(id, delay);
      }
    } finally {
      inFlight.delete(id);
      inFlightConfigs.delete(id);
      notify();
      if (pending.has(id) && !timers.has(id)) schedule(id, 0); // follow-up for mid-flight edits
    }
  }

  function schedule(id: string, delay: number): void {
    const t = timers.get(id);
    if (t) clearTimeout(t);
    timers.set(id, setTimeout(() => { timers.delete(id); void save(id); }, delay));
  }

  return {
    commit(id, config, delay = debounce) {
      pending.set(id, config);
      schedule(id, delay);
      notify();
    },
    async flush(id) {
      const t = timers.get(id);
      if (t) { clearTimeout(t); timers.delete(id); }
      await save(id);
    },
    async flushAll() {
      await Promise.all([...new Set([...pending.keys(), ...timers.keys()])].map((id) => this.flush(id)));
    },
    flushAllKeepalive() {
      if (!deps.patchKeepalive) return;
      // Everything not yet durable gets re-fired: pending edits AND in-flight
      // saves — the unload aborts an in-flight save's normal fetch, making it
      // the edit MOST at risk, not a covered one. Pending wins when both exist
      // for an id (it's the newer state). Tradeoff: re-firing an in-flight save
      // can double-write if the original lands anyway — harmless on unload (an
      // idempotent full-config PATCH; a 409 is ignored by the keepalive path).
      // knownRevs wins over getRev for the same reason flush does.
      for (const [id, config] of inFlightConfigs) {
        if (pending.has(id)) continue;
        deps.patchKeepalive(id, config, knownRevs.get(id) ?? deps.getRev?.(id));
      }
      for (const [id, config] of pending) {
        deps.patchKeepalive(id, config, knownRevs.get(id) ?? deps.getRev?.(id));
      }
    },
    status() {
      if (errored.size) return "error";
      if (inFlight.size || pending.size || timers.size) return "saving";
      return "idle";
    },
    subscribe(fn) { listeners.add(fn); return () => { listeners.delete(fn); }; },
    forget(id) {
      const t = timers.get(id);
      if (t) clearTimeout(t);
      timers.delete(id); pending.delete(id); errored.delete(id); inFlight.delete(id);
      inFlightConfigs.delete(id);
      knownRevs.delete(id);
      notify();
    },
  };
}
