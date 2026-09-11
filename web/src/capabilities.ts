import type { Me, Role, WorkspaceId } from "./types";

export type Capability =
  | "questions"
  | "analytics"
  | "products.search"
  | "products.compare"
  | "products.references"
  | "listing_checks"
  | "sourcing"
  | "drafts.create"
  | "drafts.read"
  | "drafts.review"
  | "drafts.export"
  | "feedback"
  | "admin";

const ROLE_CAPABILITIES: Record<Role, Capability[]> = {
  viewer: ["questions", "products.search", "products.compare", "feedback"],
  analyst: ["questions", "analytics", "products.search", "products.compare", "products.references", "sourcing", "feedback"],
  catalog_editor: ["questions", "products.search", "products.compare", "products.references", "listing_checks", "feedback"],
  drafter: ["questions", "products.search", "products.compare", "drafts.create", "drafts.read", "drafts.export", "feedback"],
  reviewer: ["questions", "products.search", "products.compare", "listing_checks", "sourcing", "drafts.read", "drafts.review", "drafts.export", "feedback"],
  admin: ["questions", "analytics", "products.search", "products.compare", "products.references", "listing_checks", "sourcing", "drafts.create", "drafts.read", "drafts.review", "drafts.export", "feedback", "admin"],
};

export function effectiveCapabilities(me: Me | null, roles: Role[]): Set<Capability> {
  if (me?.capabilities?.length) return new Set(me.capabilities as Capability[]);
  return new Set(roles.flatMap((role) => ROLE_CAPABILITIES[role] ?? []));
}

export function canOpenWorkspace(capabilities: Set<Capability>, workspace: WorkspaceId): boolean {
  if (workspace === "knowledge") return capabilities.has("questions") || capabilities.has("analytics");
  if (workspace === "catalog") {
    return [...capabilities].some((capability) => capability.startsWith("products.") || capability === "listing_checks");
  }
  return [...capabilities].some((capability) => capability === "sourcing" || capability.startsWith("drafts."));
}
