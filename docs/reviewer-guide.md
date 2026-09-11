# Reviewer guide

Rationale: [architecture.md](architecture.md) §4.C. Endpoints: `backend/drafting/service.py`, `backend/api/router.py`.

Status labels: **implemented**, **planned**.

## What a reviewer does

1. A drafter (or admin) creates a job with `POST /v1/drafts`.
2. The server fills the template, copies brief fields, and leaves unknown mandatory values as placeholders (`[unknown — do not invent]`).
3. The draft enters `awaiting_review` with a SHA-256 `revision_hash` of the canonical JSON content.
4. A **different** principal with `drafts.review` records `approved` or `rejected` against that exact hash.
5. Final export is allowed only after `approved`.

Reviewers do not select sourcing winners, suspend listings, or publish policy. Findings are prioritization scores, not accusations.

## Templates

| `template_kind` | Required section headings |
|---|---|
| `equipment_requirements` | Purpose, Requirements, Quantities, Acceptance |
| `maintenance_service` | Purpose, Scope, Service levels, Acceptance |
| `installation_work` | Purpose, Site constraints, Work description, Acceptance |
| `recurring_service` | Purpose, Coverage, Exclusions, Acceptance |

Mandatory brief keys: `purpose`, `quantities`, `delivery_constraints`, `acceptance`. Missing keys are listed under `unresolved_assumptions`. The model must not invent them.

Policy retrieval for drafts is separate from historical examples. Historical wording **must not** override current published policy. Historical-example corpus: **planned**.

## Self-approval ban

Authors cannot approve their own drafts.

- Role gate: `drafter` has `drafts.create` but not `drafts.review`.
- Principal gate: `if draft.author_id == auth.principal_id` → 403 even for `admin`.
- Tests: `tests/test_capabilities.py::test_draft_self_approval_blocked_and_export_gate`.

Use a second person (`reviewer@marketdesk.test` in the harbor seed).

## Revision hash

`POST /v1/drafts/{id}/reviews` body:

```json
{
  "decision": "approved",
  "reason": "complete",
  "revision_hash": "<sha256 of current revision content>"
}
```

If the hash is not the current revision: **409**.

How to obtain the hash:

- `GET /v1/drafts` lists workspace drafts the caller may inspect (`drafts.read`). Reviewers default to `awaiting_review`.
- `GET /v1/drafts/{id}` returns `revision_hash` and content for the same capability.

A reviewer-only principal can inspect and approve without an out-of-band handoff. Authors still cannot approve their own drafts.

Any later content edit must create a new revision and invalidate approval. Edit API: **planned**.

## Export gate

`POST /v1/drafts/{id}/exports` requires:

1. Capability `drafts.export` (drafter, reviewer, admin), and
2. `draft.state == approved`

Otherwise 403 `final export requires an approved revision`. Unapproved text may be inspected in the API response for roles that can read the draft; it is not a downloadable final file. Watermarked review view: **planned**.

The server cannot prevent manual copy of visible text.

## Review checklist

- Required sections present; placeholders still visible where the brief was empty.
- Numbers in the draft match the brief and cited policy, not invented values.
- Citations (when present) resolve through `/v1/documents/{document_id}` for this reviewer.
- No current-policy claim grounded only in a historical example.
- Decision recorded with reason; optimistic hash matches what was read.

Finding boards (`new → triaged → investigating → resolved | dismissed`) are **planned** as a reviewer workflow; detectors today insert findings in `new` or `not_evaluable`.
