# Decision records

Format from [architecture.md](architecture.md) §7 close-out. Planning scores ≠ acceptance; see [eval-rubric.md](eval-rubric.md).

Statuses: `planned` | `implemented_unverified` | `verified` | `blocked`.

---

## DEC-SEARCH-001 — PostgreSQL full-text + pgvector, not OpenSearch

```text
decision_id: DEC-SEARCH-001
selected_option: PostgreSQL 16 with pgvector and tsvector; OpenSearch deferred
alternative_considered: Dedicated OpenSearch (or similar) cluster for k-NN with in-query filters
reason: Serious-pilot corpus (~1.2M chunks planned) can start in Postgres without a second cluster or outbox lag. Postgres stays authoritative for visibility, versions, and source text.
measurable_gate: Introduce OpenSearch only if measured PostgreSQL-only p95 retrieval misses targets with insufficient headroom, or measured production chunks are substantially above 1.2 million (architecture §2, B-T2-05). The 1.2 million planning baseline is not the trigger.
evidence_location: docker-compose.yml; backend/db.py; backend/retrieval/service.py; docs/architecture.md §2
owner_role: platform
dependencies: embedding dimension frozen at 1024; outbox table exists for a later projector
review_milestone: first production-scale retrieval benchmark
early_reconsideration_trigger: Recall@20 or p95 latency miss on the bilingual retrieval set while Postgres is the only index
status: implemented_unverified
```

Do not build OpenSearch for the first release.

---

## DEC-WF-001 — Bounded Python workflows, no LangChain

```text
decision_id: DEC-WF-001
selected_option: Explicit FastAPI services and typed gateways (no LangChain)
alternative_considered: LangChain / generic agent loop with tool-calling
reason: Authorization, retries, provenance, and evaluation are easier to inspect as functions. MCP is an integration adapter, not the orchestrator. Arbitrary SQL/Python tools are excluded.
measurable_gate: Feature modules call require()/get_auth and analytics parameterized statements; MCP has no approve/publish/SQL tools (C-T3-10, A-T2-06).
evidence_location: backend/workflows/qa.py; backend/analytics/service.py; backend/integrations/mcp_server.py; AGENTS.md
owner_role: backend
dependencies: model gateway protocol; capability map
review_milestone: independent injection suite
early_reconsideration_trigger: A demonstrated task that these bounded workflows cannot complete after evaluation, not a preference for an agent framework
status: implemented_unverified
```

---

## DEC-MODEL-001 — Fixture gateway is the default provider

```text
decision_id: DEC-MODEL-001
selected_option: MODEL_PROVIDER=fixture by default (CI, seed, local)
alternative_considered: Default to a hosted provider for all runs
reason: Deterministic tests and seed must not require network or secrets. Hosted/private are explicit opt-in. Missing HOSTED_MODEL_API_KEY must not fall back to fixture when provider is hosted.
measurable_gate: uv run pytest passes with MODEL_PROVIDER=fixture; hosted provider without a key raises RuntimeError (A-T1-03).
evidence_location: backend/model_gateway/base.py; tests/conftest.py; .env.example; docs/model-card.md
owner_role: backend
dependencies: fixture vectors (multilingual embedding model planned)
review_milestone: first hosted evaluation run with a pinned model revision
early_reconsideration_trigger: Fixture answers masking retrieval failures on the labeled set
status: implemented_unverified
```

Embeddings and rerank remain fixture even when generation is hosted or private, until the selected multilingual models are wired.

---

## DEC-AUTH-001 — Demo JWT for local identity

```text
decision_id: DEC-AUTH-001
selected_option: AUTH_MODE=demo HS256 JWT from POST /v1/auth/demo
alternative_considered: Require OIDC for every local boot
reason: Harbor seed users need a one-command login. Production identity is adopted OIDC (architecture §10), not a custom IdP.
measurable_gate: Demo login disabled when AUTH_MODE!=demo; OIDC verification of issuer, audience, JWKS before any shared deployment (B-T1-03, A-T2-05).
evidence_location: backend/auth/security.py; backend/api/router.py; docs/access-control.md
owner_role: backend
dependencies: seed principals; JWT_SECRET rotation
review_milestone: first non-local deployment
early_reconsideration_trigger: Demo auth reachable outside local/dev, or JWT_SECRET left at the example value
status: implemented_unverified
```

OIDC verification is implemented in `get_auth` with deterministic JWKS tests. A production identity-provider integration and key-rotation exercise remain unverified.

---

## DEC-MODEL-002 — Configured OpenAI-compatible hosted endpoint

```text
decision_id: DEC-MODEL-002
selected_option: Hosted generation via an explicitly configured OpenAI-compatible endpoint and model
alternative_considered: Other hosted catalogs; private-only generation for all profiles
reason: One configured endpoint, explicit API key, no silent switch to another provider. Private profile uses an internal vLLM-compatible model and must not call the hosted endpoint when PRIVATE_EGRESS_BLOCKED=true.
measurable_gate: Hosted calls use HOSTED_MODEL_BASE_URL/HOSTED_MODEL_API_KEY only; private+egress-blocked+hosted raises; blocked-egress integration test before private production (architecture §6 private deployment gate).
evidence_location: backend/config.py; backend/model_gateway/base.py; docs/model-card.md
owner_role: platform
dependencies: DEC-MODEL-001; local embeddings (planned) so hosted profile still does not send corpus vectors to an external provider unless that is later approved
review_milestone: pinned model revision + Q&A/citation gates on a frozen split
early_reconsideration_trigger: Quality, cost, or data-handling miss versus the frozen eval set; or a requirement that hosted generation leave this provider
status: implemented_unverified
```

Architecture.md §2 still mentions earlier catalog candidates as planning history. Runtime and this record are authoritative for hosted generation.
