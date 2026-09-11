import { useSyncExternalStore } from "react";
import type {
  AdminEntry,
  AnalyticsResult,
  CatalogList,
  CompareResult,
  DraftCreateResult,
  DraftListItem,
  DraftView,
  Envelope,
  Finding,
  Health,
  JobView,
  Lang,
  Me,
  Product,
  QuestionResult,
  Session,
  SourceView,
  SourcingEvent,
} from "./types";

const SESSION_KEY = "marketdesk.session";
const LANG_KEY = "marketdesk.lang";
const DRAFT_KEY = "marketdesk.lastDraft";

type Listener = () => void;
let adminLog: AdminEntry[] = [];
const adminListeners = new Set<Listener>();
let sessionEpoch = 0;

function emitAdmin() {
  for (const listener of adminListeners) listener();
}

function subscribeAdmin(listener: Listener) {
  adminListeners.add(listener);
  return () => adminListeners.delete(listener);
}

export function getAdminLog() {
  return adminLog;
}

export function clearAdminLog() {
  adminLog = [];
  emitAdmin();
}

export function useAdminLog() {
  return useSyncExternalStore(subscribeAdmin, getAdminLog, getAdminLog);
}

export function readSession(): Session | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Session;
    if (!parsed.access_token) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function writeSession(session: Session) {
  sessionEpoch += 1;
  localStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

export function clearSession() {
  sessionEpoch += 1;
  localStorage.removeItem(SESSION_KEY);
  localStorage.removeItem(DRAFT_KEY);
  clearAdminLog();
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event("marketdesk:logout"));
  }
}

export function readLang(): Lang {
  const value = localStorage.getItem(LANG_KEY);
  return value === "id" ? "id" : "en";
}

export function writeLang(lang: Lang) {
  localStorage.setItem(LANG_KEY, lang);
}

export type CachedDraft = {
  id: string;
  title: string;
  state: string;
  revision_hash: string | null;
  workspace_id?: string;
};

export function persistableCachedDraft(
  draft: CachedDraft & { content?: unknown; unresolved_assumptions?: unknown },
  workspaceId?: string,
): CachedDraft {
  const workspace_id = draft.workspace_id ?? workspaceId;
  const next: CachedDraft = {
    id: draft.id,
    title: draft.title,
    state: draft.state,
    revision_hash: draft.revision_hash,
  };
  if (workspace_id) next.workspace_id = workspace_id;
  return next;
}

export function parseCachedDraft(raw: string | null, session: Session | null): CachedDraft | null {
  if (!session || !raw) return null;
  try {
    const parsed = JSON.parse(raw) as CachedDraft;
    if (!parsed?.id || typeof parsed.id !== "string") return null;
    if (parsed.workspace_id && parsed.workspace_id !== session.workspace_id) return null;
    return persistableCachedDraft(parsed, session.workspace_id);
  } catch {
    return null;
  }
}

export function shouldRestoreDraftCache(status: number): boolean {
  return status !== 401 && status !== 403 && status !== 404;
}

export function cachedDraftForLoadFailure(
  status: number,
  cached: CachedDraft | null,
  requestedId: string,
): CachedDraft | null {
  if (!shouldRestoreDraftCache(status)) return null;
  if (!cached || cached.id !== requestedId) return null;
  return cached;
}

export function mergeProductsById(results: Product[], selected: Product[]): Product[] {
  const map = new Map<string, Product>();
  for (const item of results) {
    if (item?.id) map.set(item.id, item);
  }
  for (const item of selected) {
    if (item?.id && !map.has(item.id)) map.set(item.id, item);
  }
  return [...map.values()];
}

export function readCachedDraft(): CachedDraft | null {
  try {
    return parseCachedDraft(localStorage.getItem(DRAFT_KEY), readSession());
  } catch {
    return null;
  }
}

export function writeCachedDraft(draft: CachedDraft) {
  const session = readSession();
  if (!session) return;
  localStorage.setItem(DRAFT_KEY, JSON.stringify(persistableCachedDraft(draft, session.workspace_id)));
}

export function clearCachedDraft() {
  localStorage.removeItem(DRAFT_KEY);
}

export class ApiError extends Error {
  status: number;
  body: unknown;
  path: string;

  constructor(status: number, message: string, body: unknown, path: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
    this.path = path;
  }
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function formatDetail(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (item && typeof item === "object" && "msg" in item) {
            return String((item as { msg: unknown }).msg);
          }
          return JSON.stringify(item);
        })
        .join("; ");
    }
    return JSON.stringify(detail);
  }
  if (typeof body === "string" && body) return body;
  return status ? `HTTP ${status}` : "Network error";
}

function extractWarnings(body: unknown): string[] {
  if (body && typeof body === "object" && "warnings" in body) {
    const warnings = (body as { warnings: unknown }).warnings;
    if (Array.isArray(warnings)) return warnings.map(String);
  }
  return [];
}

function redact(value: unknown): unknown {
  if (value == null) return value;
  if (typeof value === "string") {
    if (/^Bearer\s+/i.test(value)) return "Bearer ***";
    return value;
  }
  if (Array.isArray(value)) return value.map(redact);
  if (typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, nested] of Object.entries(value as Record<string, unknown>)) {
      if (/token|authorization|secret|password/i.test(key)) out[key] = "***";
      else out[key] = redact(nested);
    }
    return out;
  }
  return value;
}

function pushLog(entry: Omit<AdminEntry, "id" | "at">) {
  adminLog = [
    {
      id: crypto.randomUUID(),
      at: new Date().toISOString(),
      ...entry,
      request: redact(entry.request),
      response: redact(entry.response),
    },
    ...adminLog,
  ].slice(0, 40);
  emitAdmin();
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  opts?: { auth?: boolean },
): Promise<T> {
  const session = readSession();
  const headers: Record<string, string> = {
    Accept: "application/json",
    "X-Request-Id": crypto.randomUUID(),
  };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (opts?.auth !== false && session?.access_token) {
    headers.Authorization = `Bearer ${session.access_token}`;
  }

  const epoch = sessionEpoch;
  try {
    const res = await fetch(path, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    const text = await res.text();
    if (opts?.auth !== false && epoch !== sessionEpoch) {
      throw new ApiError(0, "Session ended", null, path);
    }
    const responseBody = text ? safeJson(text) : null;
    pushLog({
      method,
      path,
      request: body ?? null,
      status: res.status,
      response: responseBody,
      warnings: extractWarnings(responseBody),
    });
    if (!res.ok) {
      if (res.status === 401) clearSession();
      throw new ApiError(res.status, formatDetail(responseBody, res.status), responseBody, path);
    }
    return responseBody as T;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    const message = err instanceof Error ? err.message : "Network error";
    if (opts?.auth !== false && epoch !== sessionEpoch) {
      throw new ApiError(0, message, err, path);
    }
    pushLog({
      method,
      path,
      request: body ?? null,
      status: 0,
      response: { error: message },
      warnings: [],
    });
    throw new ApiError(0, message, err, path);
  }
}

export const api = {
  health: () => request<Health>("GET", "/health", undefined, { auth: false }),
  login: (email: string) =>
    request<Session>("POST", "/v1/auth/demo", { email, workspace: "harbor" }, { auth: false }),
  me: () => request<Me>("GET", "/v1/me"),
  question: (body: {
    question: string;
    language?: Lang | "mixed";
    as_of?: string | null;
  }) => request<Envelope<QuestionResult>>("POST", "/v1/questions", body),
  analytics: (body: {
    pattern: string;
    filters: Record<string, unknown>;
    group_by?: string[];
    presentation?: "table" | "bar" | "line";
  }) => request<Envelope<AnalyticsResult>>("POST", "/v1/analytics/queries", body),
  productSearch: (body: Record<string, unknown>) =>
    request<Envelope<{ items: Product[] }>>("POST", "/v1/products/search", body),
  productCompare: (product_ids: string[]) =>
    request<Envelope<CompareResult>>("POST", "/v1/products/compare", { product_ids }),
  productReferences: (id: string) =>
    request<Envelope<Record<string, unknown>>>("GET", `/v1/products/${id}/references`),
  listingChecks: (product_id: string) =>
    request<Envelope<Finding[]>>("POST", "/v1/listing-checks", { product_id }),
  catalogProducts: (params?: { limit?: number; offset?: number }) => {
    const limit = Math.min(Math.max(params?.limit ?? 50, 1), 100);
    const offset = Math.max(params?.offset ?? 0, 0);
    return request<CatalogList>("GET", `/v1/catalog/products?limit=${limit}&offset=${offset}`);
  },
  catalogEvents: () => request<{ items: SourcingEvent[] }>("GET", "/v1/catalog/events"),
  sourcing: (event_id: string) =>
    request<Envelope<Finding[]>>("POST", "/v1/sourcing-evaluations", { event_id }),
  createDraft: (body: {
    template_kind: string;
    title: string;
    brief: Record<string, string>;
    idempotency_key: string;
  }) => request<Envelope<DraftCreateResult>>("POST", "/v1/drafts", body),
  getDraft: (id: string) => request<DraftView>("GET", `/v1/drafts/${id}`),
  listDrafts: (state?: string) => {
    const query = state ? `?state=${encodeURIComponent(state)}` : "";
    return request<{ items: DraftListItem[] }>("GET", `/v1/drafts${query}`);
  },
  reviewDraft: (id: string, body: { decision: "approved" | "rejected"; reason: string; revision_hash: string }) =>
    request<Envelope<{ draft_id: string; state: string }>>("POST", `/v1/drafts/${id}/reviews`, body),
  exportDraft: (id: string) => request<Envelope<Record<string, unknown>>>("POST", `/v1/drafts/${id}/exports`),
  getJob: (id: string) => request<JobView>("GET", `/v1/jobs/${id}`),
  getSource: (id: string) => request<SourceView>("GET", `/v1/documents/${id}`),
  feedback: (body: {
    target_type: string;
    target_id: string;
    label: string;
    comment: string;
    idempotency_key: string;
  }) => request<Envelope<{ id: string }>>("POST", "/v1/feedback", body),
};

export function isForbidden(error: unknown) {
  return error instanceof ApiError && error.status === 403;
}
