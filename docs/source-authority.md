# Source authority

Rationale and planning targets: [architecture.md](architecture.md) §3. This page is the implementable contract.

Status labels: **implemented**, **fixture**, **planned**.

## Source types

`backend.domain.enums.SourceType` and `Source.authority_class` decide how a record may be used. The model does not choose the mechanism.

| Source type | Authority class | Mechanism | Notes |
|---|---|---|---|
| `policy` | `current_policy` | Versioned retrieval | Authoritative only inside recorded effective dates. Seeded as “Approved procedures”. **implemented** |
| `faq` | `guidance` | Retrieval linked to policy | Entry point only; cannot override `current_policy`. **planned** (enum exists; no FAQ corpus in seed) |
| `historical_plan` | `historical_example` | Restricted retrieval for drafting | Precedent, not current policy. **planned** |
| `product` | structured record | Catalog lookup + search | Current PostgreSQL row wins over indexed text. **implemented** in `catalog/` |
| `operational` | `operational_fact` | Parameterized read-only tools | Never answer live totals from embeddings. **implemented** in `analytics/` |
| `price_feed` | `untrusted_observation` | Licensed connector rows | Timestamped evidence; stale rows cannot silently drive a current recommendation. **implemented** |
| `image` | `untrusted_observation` | Stored object + vision check | Observations need validation. **planned** (product `image_key` exists) |
| `feedback` | n/a | Separate labeling store | Not searchable knowledge. **implemented** as `feedback` rows |

Untrusted listings and images are data, not instructions.

## Authority classes

| Class | May ground | Must not |
|---|---|---|
| `current_policy` | Requirements, prohibitions, procedures | Be overridden by FAQ, chat history, or drafts |
| `guidance` | Clarifying entry points | Override policy |
| `historical_example` | Drafting examples (up to five in the plan) | Be treated as current rules |
| `operational_fact` | Analytics totals and counts | Be retrieved as prose chunks for live numbers |
| `untrusted_observation` | Price/image/listing evidence with provenance | Become policy or a guaranteed fair price |

Q&A retrieval currently loads **published policy documents** only. Product, spend, order, and price facts go through typed services.

## Publication lifecycle

Canonical states (`LifecycleStatus`):

```text
received → quarantined → extracted → validated → awaiting_approval
  → approved → indexed → published
Any processing stage → failed
published → superseded | withdrawn
```

**implemented** fast path in `IngestionService.ingest_text`:

1. Insert document as `received`.
2. Hash body (`sha256`), store a `DocumentVersion` (`parser_version=plaintext-1`).
3. Structure-aware chunking (target ≤700 tokens, hard max 900, ≤80-token overlap when a paragraph splits).
4. Embed chunks through the model gateway.
5. If `publish=True`: version `approval_state=approved`, document `published`, outbox `document_indexed`.
6. If `publish=False`: document `awaiting_approval`; retrieval will not return it.
7. `withdraw()` sets `withdrawn` immediately. Retrieval requires `published`, so withdrawal blocks canonical access even if chunks still exist.

**implemented for the demo**: source registration, multipart upload with byte cap, PDF/text extraction, staged approval/publication, reindex, withdrawal, audit/outbox events, and document-version supersession. MIME/malware intake gates, Docling/OCR, hidden-text flags, blue/green index generations, and reconciliation of outbox vs index remain **planned**.

Visibility (`Visibility`):

| Value | Who can retrieve |
|---|---|
| `public_workspace` | Any member of the workspace |
| `restricted` | Principals whose `group_ids` overlap `document.allowed_groups`, plus `reviewer` / `admin` |
| `reviewer_only` | Reviewers and admins |

Seed example: “Restricted incident handling notes” is `restricted` with `allowed_groups=["incident-response"]`. The `restricted@marketdesk.test` viewer is in group `restricted` and must not see it.

Default Q&A uses the current approved version. Pass `as_of` on `POST /v1/questions` for an explicit historical cut. Conflicting approved sources: **planned** (ask for clarification).

## Citation contract

Every factual Q&A claim must reference an evidence ID **the server supplied**. The model may pick IDs; it may not invent viewer URLs.

Server-issued `EvidenceRef` (`backend/domain/schemas.py`):

```text
document_id
document_version_id
chunk_id
section_path
page_or_table_location
supporting_span
source_effective_date
authorized_viewer_url   # /v1/documents/{document_id}
```

`authorized_viewer_url` is an authenticated document viewer. `GET /v1/documents/{id}` loads the current authorized document version. `GET /v1/sources/{id}` loads source-catalog metadata. Unpublished documents are hidden unless the caller is a `reviewer` or `admin`.

Verification:

| Layer | Behavior | Status |
|---|---|---|
| Deterministic | Claim `evidence_id` must be in the retrieved `chunk_id` set; otherwise the claim is dropped. Answer with no remaining claims becomes `insufficient_evidence`. The fixture generator deliberately also emits `invented-id-not-in-evidence` so stripping is testable. | **implemented** in `workflows/qa.py` |
| Canonical recheck | Workspace, `published`, version `approved`, current version, visibility/groups | **implemented** in `retrieval/service.py` |
| Semantic support | Bounded verifier; at most one repair | **planned** (`VERIFY_JSON` exists on the fixture gateway but Q&A does not call it) |

Chat history is conversation context, not a citable source.

## Retrieval sequence (implemented)

1. Authenticate; derive workspace and groups from the session (never from the question).
2. Reject configured out-of-scope hints (`lottery`, `medical diagnosis`, `write malware`) as `out_of_scope`.
3. Lexical top-60 + vector top-60 on published, approved, current versions.
4. Reciprocal rank fusion (`k=60`), rerank ≤40, keep ≤10 evidence passages.
5. Generate only from that evidence block; persist an `interactions` row before returning.

Operational numbers must not be answered from this path. Use `POST /v1/analytics/queries`.
