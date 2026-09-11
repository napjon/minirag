# Access control

Rationale: [architecture.md](architecture.md) §5. Roles and capabilities below match `backend/auth/security.py`.

Status labels: **implemented**, **planned**.

## Identity

| Mode | Use | Status |
|---|---|---|
| `AUTH_MODE=demo` | `POST /v1/auth/demo` with `{email, workspace}` issues an HS256 JWT (12h, `iss`/`aud` from settings). Local default. | **implemented** |
| `AUTH_MODE=oidc` | Verify issuer, audience, JWKS. | **implemented** (`decode_access_token` validates a pinned algorithm allowlist, issuer, audience, expiry, required claims, and `kid`; subject is resolved to a local principal) |

Principal and workspace come from verified credentials. Model-generated arguments never set them.

`GET /v1/me` returns `principal_id`, `workspace_id`, roles, and groups.

## Roles

`backend.domain.enums.Role`:

| Role | Typical job |
|---|---|
| `viewer` | Policy Q&A, product search/compare, feedback |
| `analyst` | Operational queries, sourcing evaluations, price references |
| `catalog_editor` | Listing checks, catalog search, price references |
| `drafter` | Create drafts; export after someone else approved |
| `reviewer` | Approve/reject drafts; listing and sourcing review |
| `admin` | All of the above plus audit export |

Membership is workspace-scoped (`memberships.roles`, `memberships.group_ids`). Multiple roles are allowed.

## Capabilities

`CAPABILITIES` in `backend/auth/security.py`. `require(capability)` returns 403 on miss.

| Capability | Roles | HTTP |
|---|---|---|
| `questions` | viewer, analyst, drafter, reviewer, admin, catalog_editor | `POST /v1/questions` |
| `analytics` | analyst, admin | `POST /v1/analytics/queries` |
| `products.search` | viewer, analyst, catalog_editor, admin, drafter, reviewer | `POST /v1/products/search`, `GET /v1/catalog/products` |
| `products.compare` | same as search | `POST /v1/products/compare` |
| `products.references` | analyst, catalog_editor, admin | `GET /v1/products/{id}/references` |
| `listing_checks` | catalog_editor, admin, reviewer | `POST /v1/listing-checks`; `GET /v1/findings/{id}` when `entity_type=product` |
| `sourcing` | analyst, admin, reviewer | `POST /v1/sourcing-evaluations`, `GET /v1/catalog/events`; `GET /v1/findings/{id}` when not a product finding |
| `drafts.create` | drafter, admin | `POST /v1/drafts` |
| `drafts.read` | drafter, reviewer, admin | `GET /v1/drafts`, `GET /v1/drafts/{id}` |
| `drafts.review` | reviewer, admin | `POST /v1/drafts/{id}/reviews` |
| `drafts.export` | drafter, reviewer, admin | `POST /v1/drafts/{id}/exports` (still requires approved state) |
| `feedback` | all roles except none | `POST /v1/feedback` |
| `sources.read` | all workspace roles above | `GET /v1/sources/{id}` |
| `sources.ingest` | admin, catalog_editor | `POST /v1/documents/uploads`, `POST /v1/documents/{id}/withdraw` |
| `audit.export` | admin | `POST /v1/audit-exports` |
| `admin` | admin | reserved |

Draft inspect uses `drafts.read`. Reviewers can `GET /v1/drafts` (awaiting review by default) and `GET /v1/drafts/{id}` for revision hash and body. Drafters see their own drafts on the list. Review still requires that hash in the POST body (see [reviewer-guide.md](reviewer-guide.md)).

Self-approval is banned in `DraftingService` even if the author also has `drafts.review` (for example admin). See [reviewer-guide.md](reviewer-guide.md).

## Row-level security

On startup `init_db` `ENABLE` + `FORCE ROW LEVEL SECURITY` and creates `workspace_isolation` on:

```text
sources, documents, document_versions, chunks, products,
price_observations, spend_records, order_records, sourcing_events,
detection_findings, drafts, draft_revisions, review_decisions,
jobs, interactions, feedback, outbox_events, audit_events, memberships
```

Policy: `workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid`.

Authenticated requests call `apply_rls(session, workspace_id, principal_id)` before queries. Application SQL also filters `workspace_id == auth.workspace_id`.

**Local compose gap:** the database user is a superuser (`POSTGRES_USER=marketdesk`). Superusers bypass RLS even with `FORCE`. Treat RLS as **not proven** in the demo database. Production must use a non-owner, non-`BYPASSRLS` role; keep migrations on a separate credential (`DATABASE_ADMIN_URL`).

`principals` and `workspaces` are not RLS-gated (identity catalog).

## Search vs canonical recheck

Retrieval applies coarse filters (published, visibility, groups) in SQL, then **rechecks** workspace, publication, approval, current version, and groups before text reaches the model. Caches, if added, must include workspace, permission fingerprint, corpus revision, query, and model/prompt revision. **planned** beyond the in-request recheck.

Queued jobs store `permission_fingerprint`; replay and worker execution compare it with current
membership. Inline mode is the default demo path. In worker mode, draft jobs are claimed with a
lease and `SKIP LOCKED`, so an expired process claim can be retried without bypassing permission
checks.

## MCP restrictions

Start command, frozen tool list, and `cannot` list: [mcp.md](mcp.md). The adapter is an HTTP client (`mcp_manifest.json` + `mcp_server.py`); no second business layer.

`get_finding` uses the same capability split as REST (listing vs sourcing). `get_draft_status` calls `GET /v1/drafts/{id}` and therefore requires `drafts.read`.

Auth: `MARKETDESK_TOKEN` bearer, sent only to `MARKETDESK_API`. Never forward it to a model provider.

MCP clients **must not** be given tools that approve drafts, publish documents, change permissions, run SQL, send mail, or open arbitrary URLs. `tests/test_mcp_contract.py` asserts those names are absent.

Remote MCP OAuth discovery (issuer, audience, expiry, scopes) is **planned**.
