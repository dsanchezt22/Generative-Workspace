import type { ModuleConfig, StoredModule } from "./types";

export type SaveStatus = "idle" | "saving" | "error";

interface Deps {
  patch: (id: string, config: ModuleConfig) => Promise<StoredModule>;
  onSaved?: (m: StoredModule) => void;
  onError?: (id: string, err: unknown) => void;
  debounceMs?: number;
}

export interface ModuleSaver {
  commit(id: string, config: ModuleConfig, delay?: number): void;
  flush(id: string): Promise<void>;
  flushAll(): Promise<void>;
  status(): SaveStatus;
  subscribe(fn: () => void): () => void;
  forget(id: string): void; // module deleted — drop pending work
}

export function createModuleSaver(deps: Deps): ModuleSaver {
  const debounce = deps.debounceMs ?? 400;
  const pending = new Map<string, ModuleConfig>();
  const timers = new Map<string, ReturnType<typeof setTimeout>>();
  const inFlight = new Set<string>();
  const errored = new Set<string>();
  const listeners = new Set<() => void>();
  const retryDelay = new Map<string, number>();

  const notify = () => listeners.forEach((fn) => fn());

  async function save(id: string): Promise<void> {
    const config = pending.get(id);
    if (config === undefined || inFlight.has(id)) return;
    pending.delete(id);
    inFlight.add(id);
    notify();
    try {
      const saved = await deps.patch(id, config);
      errored.delete(id);
      retryDelay.delete(id);
      deps.onSaved?.(saved);
    } catch (err) {
      // keep the newest config: an edit made during the failed save wins
      if (!pending.has(id)) pending.set(id, config);
      errored.add(id);
      deps.onError?.(id, err);
      const delay = Math.min(retryDelay.get(id) ?? 1000, 30_000);
      retryDelay.set(id, delay * 2);
      schedule(id, delay);
    } finally {
      inFlight.delete(id);
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
      notify();
    },
  };
}
