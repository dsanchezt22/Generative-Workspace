import type { ActivityEntry, ApprovalOut, AutomationCreate, AutomationOut, AutomationPatch, DataSource, LiveValuePayload, Message, ModuleConfig, Page, ProfileKind, Snapshot, StoredModule, StudioLayout, StudioUseCase, UserProfileEntry } from "./types";
import { buildLiveQueryParams } from "./liveFormat";

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? body;
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  get refusal(): string | null {
    if (
      this.detail &&
      typeof this.detail === "object" &&
      "refusal" in (this.detail as Record<string, unknown>)
    ) {
      return String((this.detail as { refusal: unknown }).refusal);
    }
    return null;
  }
  // R-304: a clarifying-question outcome arrives as { question } — surface the
  // bare text, not the raw JSON object.
  get question(): string | null {
    if (
      this.detail &&
      typeof this.detail === "object" &&
      "question" in (this.detail as Record<string, unknown>)
    ) {
      return String((this.detail as { question: unknown }).question);
    }
    return null;
  }
  // R-902: claiming an invite while the session already belongs to a
  // different, live user arrives as 409 { rebind: "<current user name>" }.
  get rebind(): string | null {
    if (
      this.detail &&
      typeof this.detail === "object" &&
      "rebind" in (this.detail as Record<string, unknown>)
    ) {
      return String((this.detail as { rebind: unknown }).rebind);
    }
    return null;
  }
  // R-602: a stale PATCH (rev mismatch) arrives as 409 { conflict: <current
  // StoredModule> } — the loser reloads visibly instead of clobbering it.
  get conflict(): StoredModule | null {
    if (
      this.detail &&
      typeof this.detail === "object" &&
      "conflict" in (this.detail as Record<string, unknown>)
    ) {
      return (this.detail as { conflict: StoredModule }).conflict;
    }
    return null;
  }
}

// R-102: one question/answer pair from a multi-turn clarifying interview.
export interface ExchangeTurn {
  question: string;
  answer: string;
}

export interface GenerateResponse {
  module?: StoredModule | null;
  modules?: StoredModule[] | null;
  previews?: ModuleConfig[] | null;
  question?: string | null;
  degraded?: boolean | null;
  // R-103/R-301: a one-paragraph rationale for the proposal, set only on a
  // fresh (non-stub, non-cached) model response.
  plan?: string | null;
}

export const api = {
  // Invite claim (R-901-905). GET is a read-only preview (no session write);
  // POST performs the claim. See `backend/src/routes/auth.py` for the
  // security rationale (a GET must never mutate who a browser is signed in as).
  authClaimPreview: (token: string) =>
    request<{ valid: boolean; name: string }>(`/api/auth/claim?token=${encodeURIComponent(token)}`),
  authClaim: (token: string, confirm = false) =>
    request<{ ok: boolean; name: string }>("/api/auth/claim", {
      method: "POST",
      body: JSON.stringify({ token, confirm }),
    }),
  authMe: () => request<{ claimed: boolean; name: string | null }>("/api/auth/me"),

  listPages: () => request<Page[]>("/api/pages"),
  createPage: (name: string, icon?: string, parentId?: string | null) =>
    request<Page>("/api/pages", {
      method: "POST",
      body: JSON.stringify({ name, icon, parent_id: parentId ?? null }),
    }),
  updatePage: (
    id: string,
    patch: {
      name?: string;
      icon?: string | null;
      parent_id?: string | null;
      // R-504: dragging a child's portal tile persists its world placement.
      portal_x?: number | null;
      portal_y?: number | null;
      // R-504 completion: the page's own viewport (pan/zoom), saved debounced.
      view_x?: number | null;
      view_y?: number | null;
      view_zoom?: number | null;
    },
  ) => request<Page>(`/api/pages/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  // R-502: live module count per page for the portal tiles' cheap "N tools"
  // preview (one grouped COUNT server-side — no child module configs loaded).
  pageModuleCounts: () => request<Record<string, number>>("/api/pages/counts"),
  renamePage: (id: string, name: string) =>
    request<Page>(`/api/pages/${id}`, { method: "PATCH", body: JSON.stringify({ name }) }),
  reorderPages: (orderedIds: string[]) =>
    request<Page[]>("/api/pages/reorder", {
      method: "POST",
      body: JSON.stringify({ ordered_ids: orderedIds }),
    }),
  deletePage: (id: string) =>
    request<void>(`/api/pages/${id}`, { method: "DELETE" }),
  listModules: (pageId?: string, includeArchived?: boolean) => {
    const params = new URLSearchParams();
    if (pageId) params.set("page_id", pageId);
    if (includeArchived) params.set("include_archived", "1");
    const qs = params.toString();
    return request<StoredModule[]>(`/api/modules${qs ? `?${qs}` : ""}`);
  },
  seedStarter: (pageId?: string) =>
    request<StoredModule[]>(`/api/onboarding/seed${pageId ? `?page_id=${pageId}` : ""}`, {
      method: "POST",
    }),
  // R-104: per-owner, usage-seeded starter prompts (owner-scoped server-side).
  // Empty for a brand-new owner — the caller falls back to static chips.
  suggestions: (limit?: number) =>
    request<{ prompt: string }[]>(`/api/suggestions${limit ? `?limit=${limit}` : ""}`),
  // R-102 "Just build it": `buildNow` sends build_now:true so the backend forces
  // a HARD build (allow_question=False) — the skip is never re-questioned.
  generateModule: (prompt: string, pageId?: string, exchange?: ExchangeTurn[], buildNow?: boolean) =>
    request<GenerateResponse>(`/api/modules/generate${pageId ? `?page_id=${pageId}` : ""}`, {
      method: "POST",
      body: JSON.stringify({ prompt, exchange, build_now: buildNow }),
    }),
  previewModules: (prompt: string, pageId?: string, exchange?: ExchangeTurn[], buildNow?: boolean) =>
    request<GenerateResponse>(`/api/modules/preview${pageId ? `?page_id=${pageId}` : ""}`, {
      method: "POST",
      body: JSON.stringify({ prompt, exchange, build_now: buildNow }),
    }),
  // R-802: `exchange` carries the clarifying interview that produced these
  // accepted tools, so the backend accretes profile facts HERE (on a confirmed
  // accept) rather than on the discardable preview. Omitted for a fresh (no-
  // interview) proposal — a plain build accretes nothing.
  insertModules: (configs: ModuleConfig[], prompt?: string, pageId?: string, exchange?: ExchangeTurn[]) =>
    request<StoredModule[]>(`/api/modules${pageId ? `?page_id=${pageId}` : ""}`, {
      method: "POST",
      body: JSON.stringify({ configs, prompt, exchange }),
    }),
  // R-221: `hint` is the sketch snap's bounded interpretation instruction; the
  // backend folds it into the model-visible message. Omitted for plain uploads.
  // `preview` (Stage-2b/R-223 backlog): mirrors previewModules — the caller gets
  // `previews` back instead of the tools being inserted straight onto the canvas.
  generateModuleFromFile: async (
    file: File,
    prompt: string,
    pageId?: string,
    hint?: string,
    preview?: boolean,
  ): Promise<GenerateResponse> => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("prompt", prompt);
    if (hint) fd.append("hint", hint);
    if (preview) fd.append("preview", "true");
    const res = await fetch(`${BASE}/api/modules/generate_from_file${pageId ? `?page_id=${pageId}` : ""}`, {
      method: "POST",
      credentials: "include",
      body: fd, // browser sets multipart boundary; do not set Content-Type
    });
    if (!res.ok) {
      let detail: unknown = res.statusText;
      try { const b = await res.json(); detail = b.detail ?? b; } catch { /* keep */ }
      throw new ApiError(res.status, detail);
    }
    return (await res.json()) as GenerateResponse;
  },
  // R-201/204: POST the recorded ramble (webm/opus, or the browser's
  // MediaRecorder default) to the pluggable STT endpoint. Origin-gated, so a
  // same-origin fetch needs no extra auth beyond the session cookie.
  transcribe: async (blob: Blob): Promise<{ text: string }> => {
    const ext = blob.type.includes("webm")
      ? "webm"
      : blob.type.includes("ogg")
        ? "ogg"
        : blob.type.includes("mp4")
          ? "mp4"
          : blob.type.includes("wav")
            ? "wav"
            : "webm";
    const fd = new FormData();
    fd.append("file", blob, `ramble.${ext}`);
    const res = await fetch(`${BASE}/api/transcribe`, {
      method: "POST",
      credentials: "include",
      body: fd, // browser sets multipart boundary; do not set Content-Type
    });
    if (!res.ok) {
      let detail: unknown = res.statusText;
      try { const b = await res.json(); detail = b.detail ?? b; } catch { /* keep */ }
      throw new ApiError(res.status, detail);
    }
    return (await res.json()) as { text: string };
  },
  patchModule: (id: string, config: ModuleConfig, rev?: number) =>
    request<StoredModule>(`/api/modules/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ config, rev }),
    }),
  // R-1101: a fetch clone of patchModule with `keepalive: true`, so an in-flight
  // save survives the document being torn down (a normal fetch is cancelled on
  // unload). Fire-and-forget — no response is awaited during beforeunload.
  patchModuleKeepalive: (id: string, config: ModuleConfig, rev?: number) => {
    void fetch(`${BASE}/api/modules/${id}`, {
      method: "PATCH",
      credentials: "include",
      keepalive: true,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config, rev }),
      // Swallow rejection noise: a cancel-then-stay may double-write, and a stale
      // rev is handled by the normal saver path (409) — this fire-and-forget copy
      // has no one awaiting it, so an unhandled rejection is just noise.
    }).catch(() => {});
  },
  deleteModule: (id: string) =>
    request<void>(`/api/modules/${id}`, { method: "DELETE" }),
  duplicateModule: (id: string) =>
    request<StoredModule>(`/api/modules/${id}/duplicate`, { method: "POST" }),
  archiveModule: (id: string) =>
    request<StoredModule>(`/api/modules/${id}/archive`, { method: "POST" }),
  restoreModule: (id: string) =>
    request<StoredModule>(`/api/modules/${id}/restore`, { method: "POST" }),
  listArchived: () => request<StoredModule[]>("/api/modules/archived"),
  undoModule: (id: string) =>
    request<StoredModule>(`/api/modules/${id}/undo`, { method: "POST" }),
  refineModule: (id: string, prompt: string) =>
    request<StoredModule>(`/api/modules/${id}/refine`, {
      method: "POST",
      body: JSON.stringify({ prompt }),
    }),
  // R-701/R-704: the live-value refresh hook's fetch (`useLiveValue.ts`). GET,
  // owner-gated via the session cookie (request() already sends
  // credentials:"include"); query→params built by the shared, tested builder
  // (weather: place OR lat+lon; nutrition: food).
  liveValue: (provider: DataSource["provider"], query: DataSource["query"], refreshSecs: number) =>
    request<LiveValuePayload>(`/api/live/${provider}?${buildLiveQueryParams(provider, query, refreshSecs)}`),

  workspaceInsights: (pageId?: string) =>
    request<GenerateResponse>(
      `/api/workspace/insights${pageId ? `?page_id=${pageId}` : ""}`,
      { method: "POST" },
    ),
  createSnapshot: (pageId: string, label: string) =>
    request<Snapshot>(`/api/pages/${pageId}/snapshots`, { method: "POST", body: JSON.stringify({ label }) }),
  listSnapshots: (pageId: string) =>
    request<Snapshot[]>(`/api/pages/${pageId}/snapshots`),
  restoreSnapshot: (id: string) =>
    request<void>(`/api/snapshots/${id}/restore`, { method: "POST" }),
  deleteSnapshot: (id: string) =>
    request<void>(`/api/snapshots/${id}`, { method: "DELETE" }),
  listConversation: (pageId?: string) =>
    request<Message[]>(`/api/conversations${pageId ? `?page_id=${pageId}` : ""}`),
  clearConversation: (pageId?: string) =>
    request<void>(`/api/conversations${pageId ? `?page_id=${pageId}` : ""}`, {
      method: "DELETE",
    }),

  // R-801: the "remembers you" profile surface — owner-gated CRUD over the
  // facts Trus has learned about the caller (ProfilePanel). All owner-scoped
  // server-side; request() already sends credentials:"include".
  profileList: () => request<UserProfileEntry[]>("/api/profile"),
  profileAdd: (kind: ProfileKind, text: string) =>
    request<UserProfileEntry>("/api/profile", {
      method: "POST",
      body: JSON.stringify({ kind, text }),
    }),
  profileUpdate: (id: string, text: string) =>
    request<UserProfileEntry>(`/api/profile/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ text }),
    }),
  profileDelete: (id: string) =>
    request<void>(`/api/profile/${id}`, { method: "DELETE" }),
  // R-804/R-1003: real erasure — the backend hard-DELETEs every fact for this owner.
  profileClear: () => request<{ deleted: number }>("/api/profile", { method: "DELETE" }),

  // V2 Pulse — the always-on trust spine (automations + approvals + activity).
  // All owner-scoped server-side; request() already sends credentials:"include".
  // The backend lands these contracts in the parallel A1 wave (DESIGN-autonomy
  // §4.2, reconciled ruling 4) — until then they 404, handled by callers.
  listAutomations: () => request<{ automations: AutomationOut[] }>("/api/automations"),
  createAutomation: (body: AutomationCreate) =>
    request<AutomationOut>("/api/automations", { method: "POST", body: JSON.stringify(body) }),
  patchAutomation: (id: string, patch: AutomationPatch) =>
    request<AutomationOut>(`/api/automations/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteAutomation: (id: string) =>
    request<void>(`/api/automations/${id}`, { method: "DELETE" }),
  // Run-now through the same requires_approval/park/execute path as the scheduler:
  // either it ran (activity) or it parked as an approval (approval), never both.
  runAutomation: (id: string) =>
    request<{ activity: ActivityEntry | null; approval: ApprovalOut | null }>(
      `/api/automations/${id}/run`,
      { method: "POST" },
    ),
  listApprovals: () =>
    request<{ approvals: ApprovalOut[]; pending_count: number }>("/api/approvals"),
  // The cheap badge poll — one indexed COUNT.
  approvalCount: () => request<{ pending: number }>("/api/approvals/count"),
  // Approve/reject return the resolved approval + the journal row it produced,
  // so the panel reconciles optimistically (remove the card, prepend the entry).
  // 409 { detail: { state } } on a double-tap or expiry — the loser learns honestly.
  approve: (id: string) =>
    request<{ approval: ApprovalOut; activity: ActivityEntry }>(
      `/api/approvals/${id}/approve`,
      { method: "POST" },
    ),
  reject: (id: string) =>
    request<{ approval: ApprovalOut; activity: ActivityEntry }>(
      `/api/approvals/${id}/reject`,
      { method: "POST" },
    ),
  // Newest-first, keyset pagination on created_at (pass the oldest loaded row's
  // created_at as `before` to page back).
  listActivity: (before?: string) =>
    request<{ entries: ActivityEntry[] }>(
      `/api/activity?limit=50${before ? `&before=${encodeURIComponent(before)}` : ""}`,
    ),

  // Layout Studio
  studioUseCases: () => request<StudioUseCase[]>("/api/studio/use-cases"),
  studioGenerate: (key: string, n = 4) =>
    request<StudioLayout[]>(`/api/studio/use-cases/${key}/generate?n=${n}`, { method: "POST" }),
  studioLayouts: (useCase?: string) =>
    request<StudioLayout[]>(`/api/studio/layouts${useCase ? `?use_case=${useCase}` : ""}`),
  studioDeleteLayout: (id: string) =>
    request<void>(`/api/studio/layouts/${id}`, { method: "DELETE" }),
  studioPromote: (id: string) =>
    request<{ ok: boolean; seed_prompt: string; library: { entries: number; hits: number } }>(
      `/api/studio/layouts/${id}/promote`, { method: "POST" }),
  studioImport: async (key: string, opts: { file?: File; url?: string }): Promise<StudioLayout> => {
    const fd = new FormData();
    if (opts.file) fd.append("file", opts.file);
    if (opts.url) fd.append("image_url", opts.url);
    const res = await fetch(`${BASE}/api/studio/use-cases/${key}/import`, {
      method: "POST", credentials: "include", body: fd, // browser sets multipart boundary
    });
    if (!res.ok) {
      let detail: unknown = res.statusText;
      try { const b = await res.json(); detail = b.detail ?? b; } catch { /* keep */ }
      throw new ApiError(res.status, detail);
    }
    return (await res.json()) as StudioLayout;
  },
  // Staged, high-fidelity capture: full IR → transform → coverage score → auto-seed.
  studioCapture: async (
    key: string,
    opts: { file?: File; url?: string; matchColors?: boolean },
  ): Promise<StudioLayout> => {
    const fd = new FormData();
    if (opts.file) fd.append("file", opts.file);
    if (opts.url) fd.append("image_url", opts.url);
    fd.append("match_colors", opts.matchColors ? "true" : "false");
    const res = await fetch(`${BASE}/api/studio/use-cases/${key}/capture`, {
      method: "POST", credentials: "include", body: fd,
    });
    if (!res.ok) {
      let detail: unknown = res.statusText;
      try { const b = await res.json(); detail = b.detail ?? b; } catch { /* keep */ }
      throw new ApiError(res.status, detail);
    }
    return (await res.json()) as StudioLayout;
  },
};
