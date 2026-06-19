import type { Message, ModuleConfig, Page, Snapshot, StoredModule, StudioLayout, StudioUseCase } from "./types";

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
}

export interface GenerateResponse {
  module?: StoredModule | null;
  modules?: StoredModule[] | null;
  previews?: ModuleConfig[] | null;
  question?: string | null;
}

export const api = {
  listPages: () => request<Page[]>("/api/pages"),
  createPage: (name: string, icon?: string, parentId?: string | null) =>
    request<Page>("/api/pages", {
      method: "POST",
      body: JSON.stringify({ name, icon, parent_id: parentId ?? null }),
    }),
  updatePage: (id: string, patch: { name?: string; icon?: string | null; parent_id?: string | null }) =>
    request<Page>(`/api/pages/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  renamePage: (id: string, name: string) =>
    request<Page>(`/api/pages/${id}`, { method: "PATCH", body: JSON.stringify({ name }) }),
  reorderPages: (orderedIds: string[]) =>
    request<Page[]>("/api/pages/reorder", {
      method: "POST",
      body: JSON.stringify({ ordered_ids: orderedIds }),
    }),
  deletePage: (id: string) =>
    request<void>(`/api/pages/${id}`, { method: "DELETE" }),
  listModules: (pageId?: string) =>
    request<StoredModule[]>(`/api/modules${pageId ? `?page_id=${pageId}` : ""}`),
  seedStarter: (pageId?: string) =>
    request<StoredModule[]>(`/api/onboarding/seed${pageId ? `?page_id=${pageId}` : ""}`, {
      method: "POST",
    }),
  generateModule: (prompt: string, pageId?: string) =>
    request<GenerateResponse>(`/api/modules/generate${pageId ? `?page_id=${pageId}` : ""}`, {
      method: "POST",
      body: JSON.stringify({ prompt }),
    }),
  previewModules: (prompt: string, pageId?: string) =>
    request<GenerateResponse>(`/api/modules/preview${pageId ? `?page_id=${pageId}` : ""}`, {
      method: "POST",
      body: JSON.stringify({ prompt }),
    }),
  insertModules: (configs: ModuleConfig[], prompt?: string, pageId?: string) =>
    request<StoredModule[]>(`/api/modules${pageId ? `?page_id=${pageId}` : ""}`, {
      method: "POST",
      body: JSON.stringify({ configs, prompt }),
    }),
  generateModuleFromFile: async (file: File, prompt: string, pageId?: string): Promise<GenerateResponse> => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("prompt", prompt);
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
  patchModule: (id: string, config: ModuleConfig) =>
    request<StoredModule>(`/api/modules/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ config }),
    }),
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
