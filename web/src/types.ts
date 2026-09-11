export type Lang = "en" | "id";

export type WorkspaceId = "knowledge" | "catalog" | "planning";

export type Role =
  | "viewer"
  | "analyst"
  | "catalog_editor"
  | "drafter"
  | "reviewer"
  | "admin";

export type Session = {
  access_token: string;
  token_type?: string;
  workspace_id: string;
  principal_id: string;
  roles: Role[];
  display_name: string;
  email: string;
};

export type Me = {
  principal_id: string;
  workspace_id: string;
  email: string;
  display_name: string;
  roles: Role[];
  groups: string[];
  capabilities?: string[];
};

export type Health = {
  ok: boolean;
  profile: string;
  provider: string;
  egress_blocked: boolean;
};

export type EvidenceRef = {
  document_id: string;
  document_version_id: string;
  chunk_id: string;
  section_path: string;
  page_or_table_location: string;
  supporting_span: string;
  source_effective_date: string | null;
  authorized_viewer_url: string;
};

export type Envelope<T = unknown> = {
  request_id: string;
  status: string;
  result: T;
  evidence: EvidenceRef[];
  warnings: string[];
  execution_manifest_id: string | null;
};

export type QuestionResult = {
  status: string;
  answer: string | null;
  language: string;
  limitations: string | null;
  claims: Array<Record<string, unknown>>;
};

export type AnalyticsResult = {
  pattern: string;
  filters: Record<string, unknown>;
  group_by: string[];
  freshness?: string;
  row_count: number;
  rows: Array<Record<string, unknown>>;
  presentation?: string;
};

export type Product = {
  id: string;
  sku: string;
  title: string;
  category: string;
  list_price: string;
  currency?: string;
  unit?: string;
  location?: string;
  attributes?: Record<string, unknown>;
  available?: boolean;
  score?: number;
  reasons?: string[];
};

export type CatalogList = { items: Product[]; limit?: number; offset?: number };

export type CompareResult = {
  products: Product[];
  missing: string[];
};

export type Finding = {
  id: string;
  detector_id: string;
  detector_version: string;
  severity: string;
  state: string;
  explanation: string;
  evidence: Record<string, unknown>;
};

export type SourcingEvent = {
  id: string;
  title: string;
  category: string;
  participant_count: number;
};

export type DraftView = {
  id: string;
  title: string;
  state: string;
  author_id: string;
  revision_hash: string | null;
  content: Record<string, unknown> | null;
  unresolved_assumptions: string[];
};

export type DraftListItem = {
  id: string;
  title: string;
  state: string;
  author_id: string;
  revision_hash: string | null;
};

export type DraftCreateResult = {
  job_id: string;
  result: { draft_id?: string; state?: string } | null;
};

export type JobView = {
  id: string;
  job_type: string;
  state: string;
  progress: Record<string, unknown>;
  result: { draft_id?: string; state?: string } | null;
  error: string | null;
};

export type SourceView = {
  id: string;
  title: string;
  topic: string;
  status: string;
  effective_from: string | null;
  text: string;
};

export type AdminEntry = {
  id: string;
  at: string;
  method: string;
  path: string;
  request: unknown;
  status: number;
  response: unknown;
  warnings: string[];
};

export const DEMO_USERS = [
  { email: "admin@marketdesk.test", role: "admin" },
  { email: "analyst@marketdesk.test", role: "analyst" },
  { email: "reviewer@marketdesk.test", role: "reviewer" },
  { email: "drafter@marketdesk.test", role: "drafter" },
  { email: "catalog@marketdesk.test", role: "catalog_editor" },
  { email: "restricted@marketdesk.test", role: "viewer" },
] as const;

export const ANALYTICS_PATTERNS = [
  "spending_by_period",
  "order_counts_by_status",
  "supplier_concentration",
  "price_variation",
  "additional_service_charges",
  "sourcing_outcomes",
] as const;

export const CATEGORIES = [
  "network-gear",
  "site-power",
  "field-tools",
  "maintenance",
  "installation",
] as const;

export const TEMPLATE_KINDS = [
  "equipment_requirements",
  "maintenance_service",
  "installation_work",
  "recurring_service",
] as const;

export const ANSWER_STATUSES = [
  "answered",
  "needs_clarification",
  "insufficient_evidence",
  "out_of_scope",
  "unavailable",
] as const;
