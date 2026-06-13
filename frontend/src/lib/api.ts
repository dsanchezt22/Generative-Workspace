import type { ModuleConfig, Page, StoredModule } from "./types";

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
  module: StoredModule;
}

export const api = {
  listPages: () => request<Page[]>("/api/pages"),
  createPage: (name: string) =>
    request<Page>("/api/pages", { method: "POST", body: JSON.stringify({ name }) }),
  renamePage: (id: string, name: string) =>
    request<Page>(`/api/pages/${id}`, { method: "PATCH", body: JSON.stringify({ name }) }),
  deletePage: (id: string) =>
    request<void>(`/api/pages/${id}`, { method: "DELETE" }),
  listModules: (pageId?: string) =>
    request<StoredModule[]>(`/api/modules${pageId ? `?page_id=${pageId}` : ""}`),
  generateModule: (prompt: string, pageId?: string) =>
    request<GenerateResponse>(`/api/modules/generate${pageId ? `?page_id=${pageId}` : ""}`, {
      method: "POST",
      body: JSON.stringify({ prompt }),
    }),
  patchModule: (id: string, config: ModuleConfig) =>
    request<StoredModule>(`/api/modules/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ config }),
    }),
  deleteModule: (id: string) =>
    request<void>(`/api/modules/${id}`, { method: "DELETE" }),
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
};
