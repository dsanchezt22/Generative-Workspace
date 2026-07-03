import { describe, expect, it, vi } from "vitest";
import { createModuleSaver } from "./moduleSaver";
import type { ModuleConfig } from "./types";

const cfg = (title: string) => ({ title, icon: "activity", components: [] }) as unknown as ModuleConfig;
const saved = (id: string, config: ModuleConfig) =>
  ({ id, config, created_at: "", updated_at: "", page_id: null, archived: false }) as never;

describe("moduleSaver (R-602: one writer per module, no lost updates)", () => {
  it("coalesces rapid commits into one PATCH with the last config", async () => {
    vi.useFakeTimers();
    const patch = vi.fn(async (id: string, c: ModuleConfig) => saved(id, c));
    const s = createModuleSaver({ patch });
    s.commit("m1", cfg("a"));
    s.commit("m1", cfg("b"));
    s.commit("m1", cfg("c"));
    await vi.runAllTimersAsync();
    expect(patch).toHaveBeenCalledTimes(1);
    expect(patch.mock.calls[0][1].title).toBe("c");
    vi.useRealTimers();
  });

  it("a commit landing during an in-flight save triggers a follow-up save (no dropped edit)", async () => {
    vi.useFakeTimers();
    let resolveFirst!: () => void;
    const patch = vi
      .fn<(id: string, c: ModuleConfig) => Promise<never>>()
      .mockImplementationOnce((id, c) => new Promise((res) => { resolveFirst = () => res(saved(id, c)); }))
      .mockImplementation(async (id, c) => saved(id, c));
    const s = createModuleSaver({ patch });
    s.commit("m1", cfg("first"));
    await vi.runAllTimersAsync();          // first save now in flight
    s.commit("m1", cfg("second"));         // edit while saving
    resolveFirst();
    await vi.runAllTimersAsync();
    expect(patch).toHaveBeenCalledTimes(2);
    expect(patch.mock.calls[1][1].title).toBe("second");
    vi.useRealTimers();
  });

  it("failed saves retry with backoff and expose error status", async () => {
    vi.useFakeTimers();
    const patch = vi
      .fn<(id: string, c: ModuleConfig) => Promise<never>>()
      .mockRejectedValueOnce(new Error("net"))
      .mockImplementation(async (id, c) => saved(id, c));
    const s = createModuleSaver({ patch });
    s.commit("m1", cfg("x"));
    await vi.runAllTimersAsync();
    expect(s.status()).toBe("idle");        // retried and succeeded
    expect(patch).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });
});
