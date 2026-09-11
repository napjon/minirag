import { strict as assert } from "node:assert";
import { test } from "node:test";
import { canOpenWorkspace, effectiveCapabilities } from "./capabilities";
import { dynamicLabel } from "./i18n";
import type { Me, Role } from "./types";

test("role fallback exposes only workspaces with useful capabilities", () => {
  const viewer = effectiveCapabilities(null, ["viewer"]);
  assert.equal(canOpenWorkspace(viewer, "knowledge"), true);
  assert.equal(canOpenWorkspace(viewer, "catalog"), true);
  assert.equal(canOpenWorkspace(viewer, "planning"), false);

  const reviewer = effectiveCapabilities(null, ["reviewer"]);
  assert.equal(canOpenWorkspace(reviewer, "planning"), true);
  assert.equal(reviewer.has("drafts.review"), true);
  assert.equal(reviewer.has("drafts.create"), false);
});

test("server capabilities override the role fallback", () => {
  const me = {
    principal_id: "p1",
    workspace_id: "w1",
    email: "person@example.test",
    display_name: "Person",
    roles: ["admin"] as Role[],
    groups: [],
    capabilities: ["questions"],
  } satisfies Me;
  const capabilities = effectiveCapabilities(me, me.roles);
  assert.deepEqual([...capabilities], ["questions"]);
  assert.equal(canOpenWorkspace(capabilities, "planning"), false);
});

test("dynamic result labels are bilingual while API values remain stable", () => {
  assert.equal(dynamicLabel("en", "awaiting_review"), "Awaiting review");
  assert.equal(dynamicLabel("id", "awaiting_review"), "Menunggu tinjauan");
  assert.equal(dynamicLabel("id", "network-gear"), "Perangkat jaringan");
  assert.equal(dynamicLabel("id", "spending_by_period"), "Belanja menurut periode");
});
