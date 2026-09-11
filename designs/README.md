# RAG Design Package

This folder converts the implementation plan and evaluation rubric into reviewable engineering decisions for a fictional, organization-neutral RAG platform. It intentionally contains no source-document text, names, logos, or identifying mappings.

## Planning envelope

- 100,000 documents, approximately 1.2 million searchable chunks
- 250,000 structured product records
- 50 active users
- 2 steady-state query requests per second and an 8 requests-per-second burst
- Hosted and private-network deployment profiles, introduced in stages

These figures are capacity targets, not claims about tested performance.

## Reading order

1. [Principles and decisions](01-principles-and-decisions.md)
2. [Components and boundaries](02-components-and-boundaries.md)
3. [Data and ingestion](03-data-and-ingestion.md)
4. [Retrieval and grounding](04-retrieval-and-grounding.md)
5. [Capability designs](05-capability-designs.md)
6. [Security and deployment](06-security-and-deployment.md)
7. [Evaluation and release](07-evaluation-and-release.md)
8. [Operations and scale](08-operations-and-scale.md)
9. [Ten-week delivery](09-ten-week-delivery.md)
10. [Rubric traceability](10-rubric-traceability.md)

## Evidence status

Every item must use one status:

- **Designed**: the intended behavior and acceptance method are documented.
- **Implemented**: code and configuration exist and have passed component tests.
- **Verified**: the stated evaluation ran against a versioned dataset and produced a stored report.
- **Released**: the verified version passed approval and deployment gates.

A design document never counts as runtime evidence. Each closeout record must include the build identifier, configuration hash, dataset version, command, result artifact, owner role, reviewer role, date, and exceptions.

The executable closeout workflow is documented in [`docs/release-closeout.md`](../docs/release-closeout.md). It maintains a machine-readable 48-item ledger and keeps synthetic demo evidence separate from production verification.

## Cross-cutting invariants

1. Authenticate before retrieval, generation, export, or tool execution.
2. Apply workspace and object authorization in both application code and database policy.
3. Treat retrieved and uploaded content as untrusted data.
4. Generate factual claims only from authorized evidence or typed operational query results.
5. Preserve exact source spans, version, validity dates, and stable locators.
6. Abstain when evidence is missing, conflicting, stale, or below threshold.
7. Keep generated findings and drafts pending until a human accepts them.
8. Send operational queries through parameterized, allowlisted services.
9. Record durable audit events for success, refusal, failure, approval, and export.
10. Use shared platform PostgreSQL and Redis services; do not introduce project-local database services.
