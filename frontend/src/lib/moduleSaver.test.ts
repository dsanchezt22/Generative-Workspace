import { describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import { createModuleSaver } from "./moduleSaver";
import type { ModuleConfig, StoredModule } from "./types";

const cfg = (title: string) => ({ title, icon: "activity", components: [] }) as unknown as ModuleConfig;
const saved = (id: string, config: ModuleConfig, rev = 0) =>
  ({ id, config, created_at: "", updated_at: "", page_id: null, archived: false, rev }) as never;

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

  it("a 409 rev conflict calls onConflict once and drops the pending edit — no retry loop", async () => {
    vi.useFakeTimers();
    const current = saved("m1", cfg("Tab A's latest")) as StoredModule;
    const patch = vi
      .fn<(id: string, c: ModuleConfig, rev?: number) => Promise<StoredModule>>()
      .mockRejectedValue(new ApiError(409, { conflict: current }));
    const onConflict = vi.fn();
    const s = createModuleSaver({ patch, onConflict });
    s.commit("m1", cfg("Tab B stale edit"));
    await vi.runAllTimersAsync();
    expect(patch).toHaveBeenCalledTimes(1); // no retry loop
    expect(onConflict).toHaveBeenCalledTimes(1);
    expect(onConflict).toHaveBeenCalledWith(current);
    expect(s.status()).toBe("idle"); // conflict resolved, not stuck in "error"
    vi.useRealTimers();
  });

  it("uses the server-returned rev for follow-up saves even when getRev is stale (no spurious 409)", async () => {
    // Repro of the live bug: onSaved updates React state, but the ref that
    // getRev reads syncs one render later — a setTimeout(0) follow-up flush
    // beats the effect and must NOT resend the stale rev.
    vi.useFakeTimers();
    const patch = vi
      .fn<(id: string, c: ModuleConfig, rev?: number) => Promise<StoredModule>>()
      .mockImplementation(async (id, c, rev) => saved(id, c, (rev ?? 0) + 1) as StoredModule);
    const staleGetRev = vi.fn(() => 0); // React-side rev never advances
    const s = createModuleSaver({ patch, getRev: staleGetRev });
    s.commit("m1", cfg("first"), 0);
    await vi.runAllTimersAsync(); // save resolves with rev 1
    s.commit("m1", cfg("second"), 0);
    await vi.runAllTimersAsync();
    expect(patch).toHaveBeenCalledTimes(2);
    expect(patch.mock.calls[1][2]).toBe(1); // server rev, not the stale 0
    vi.useRealTimers();
  });

  it("a 409 teaches the saver the winner's rev, so the next edit saves against it", async () => {
    vi.useFakeTimers();
    const current = saved("m1", cfg("winner"), 5) as StoredModule;
    const patch = vi
      .fn<(id: string, c: ModuleConfig, rev?: number) => Promise<StoredModule>>()
      .mockRejectedValueOnce(new ApiError(409, { conflict: current }))
      .mockImplementation(async (id, c, rev) => saved(id, c, (rev ?? 0) + 1) as StoredModule);
    const s = createModuleSaver({ patch, getRev: () => 0 });
    s.commit("m1", cfg("stale"), 0);
    await vi.runAllTimersAsync(); // 409 → learns rev 5
    s.commit("m1", cfg("re-edit after seeing latest"), 0);
    await vi.runAllTimersAsync();
    expect(patch.mock.calls[1][2]).toBe(5);
    vi.useRealTimers();
  });

  it("forget() clears the learned rev so a recreated id starts fresh", async () => {
    vi.useFakeTimers();
    const patch = vi
      .fn<(id: string, c: ModuleConfig, rev?: number) => Promise<StoredModule>>()
      .mockImplementation(async (id, c, rev) => saved(id, c, (rev ?? 0) + 1) as StoredModule);
    const s = createModuleSaver({ patch, getRev: () => 0 });
    s.commit("m1", cfg("a"), 0);
    await vi.runAllTimersAsync(); // learned rev 1
    s.forget("m1");
    s.commit("m1", cfg("b"), 0);
    await vi.runAllTimersAsync();
    expect(patch.mock.calls[1][2]).toBe(0); // back to getRev, no stale memory
    vi.useRealTimers();
  });
});
