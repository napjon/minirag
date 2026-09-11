import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";
import type { Product, Role, Session } from "./types";
import {
  cachedDraftForLoadFailure,
  clearSession,
  getAdminLog,
  mergeProductsById,
  parseCachedDraft,
  persistableCachedDraft,
  readCachedDraft,
  shouldRestoreDraftCache,
  writeCachedDraft,
  writeSession,
} from "./api";

const store = new Map<string, string>();
Object.defineProperty(globalThis, "localStorage", {
  value: {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, String(value));
    },
    removeItem: (key: string) => {
      store.delete(key);
    },
    clear: () => store.clear(),
  },
  configurable: true,
});

const session: Session = {
  access_token: "tok",
  workspace_id: "ws-1",
  principal_id: "p-1",
  roles: ["drafter"] as Role[],
  display_name: "Drafter",
  email: "drafter@marketdesk.test",
};

beforeEach(() => {
  store.clear();
});

test("persistableCachedDraft drops body fields", () => {
  const stored = persistableCachedDraft(
    {
      id: "d1",
      title: "Router refresh",
      state: "awaiting_review",
      revision_hash: "abc",
      content: { secret: "body" },
      unresolved_assumptions: ["x"],
    },
    "ws-1",
  );
  assert.deepEqual(stored, {
    id: "d1",
    title: "Router refresh",
    state: "awaiting_review",
    revision_hash: "abc",
    workspace_id: "ws-1",
  });
});

test("parseCachedDraft is null without a session and strips legacy content", () => {
  const raw = JSON.stringify({
    id: "d1",
    title: "Router refresh",
    state: "awaiting_review",
    revision_hash: "abc",
    content: { secret: "body" },
    workspace_id: "ws-1",
  });
  assert.equal(parseCachedDraft(raw, null), null);
  const parsed = parseCachedDraft(raw, session);
  assert.ok(parsed);
  assert.equal("content" in parsed, false);
  assert.equal(parseCachedDraft(raw, { ...session, workspace_id: "other" }), null);
});

test("readCachedDraft is null without a session", () => {
  store.set(
    "marketdesk.lastDraft",
    JSON.stringify({
      id: "d1",
      title: "Router refresh",
      state: "awaiting_review",
      revision_hash: "abc",
      content: { secret: "body" },
    }),
  );
  assert.equal(readCachedDraft(), null);
  writeSession(session);
  const cached = readCachedDraft();
  assert.ok(cached);
  assert.equal(cached.id, "d1");
  assert.equal("content" in cached, false);
});

test("writeCachedDraft stores metadata only and is a no-op after logout", () => {
  writeSession(session);
  writeCachedDraft({
    id: "d1",
    title: "Router refresh",
    state: "awaiting_review",
    revision_hash: "abc",
  });
  const persisted = JSON.parse(store.get("marketdesk.lastDraft") ?? "{}") as Record<string, unknown>;
  assert.equal(persisted.id, "d1");
  assert.equal("content" in persisted, false);
  assert.equal("unresolved_assumptions" in persisted, false);
  clearSession();
  assert.equal(store.has("marketdesk.session"), false);
  assert.equal(store.has("marketdesk.lastDraft"), false);
  assert.deepEqual(getAdminLog(), []);
  writeCachedDraft({
    id: "d1",
    title: "Router refresh",
    state: "awaiting_review",
    revision_hash: "abc",
  });
  assert.equal(readCachedDraft(), null);
  assert.equal(store.has("marketdesk.lastDraft"), false);
});

test("shouldRestoreDraftCache is false after 401/403/404", () => {
  assert.equal(shouldRestoreDraftCache(401), false);
  assert.equal(shouldRestoreDraftCache(403), false);
  assert.equal(shouldRestoreDraftCache(404), false);
  assert.equal(shouldRestoreDraftCache(0), true);
  assert.equal(shouldRestoreDraftCache(500), true);
});

test("cachedDraftForLoadFailure does not restore after a denied GET", () => {
  const cached = {
    id: "d1",
    title: "Router refresh",
    state: "awaiting_review",
    revision_hash: "abc",
    workspace_id: "ws-1",
  };
  assert.equal(cachedDraftForLoadFailure(403, cached, "d1"), null);
  assert.equal(cachedDraftForLoadFailure(401, cached, "d1"), null);
  assert.equal(cachedDraftForLoadFailure(404, cached, "d1"), null);
  assert.deepEqual(cachedDraftForLoadFailure(0, cached, "d1"), cached);
  assert.equal(cachedDraftForLoadFailure(500, cached, "other"), null);
});

test("mergeProductsById keeps search hits plus selected only", () => {
  const results: Product[] = [
    { id: "a", sku: "A", title: "A", category: "network-gear", list_price: "1" },
    { id: "b", sku: "B", title: "B", category: "network-gear", list_price: "2" },
  ];
  const selected: Product[] = [
    { id: "b", sku: "B", title: "B", category: "network-gear", list_price: "2" },
    { id: "c", sku: "C", title: "C", category: "site-power", list_price: "3" },
  ];
  const merged = mergeProductsById(results, selected);
  assert.deepEqual(
    merged.map((item) => item.id),
    ["a", "b", "c"],
  );
});
