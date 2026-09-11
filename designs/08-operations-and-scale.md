# Operations and Scale Design

## Serious-pilot envelope

| Dimension | Target |
|---|---:|
| Documents | 100,000 |
| Searchable chunks | approximately 1,200,000 |
| Products | 250,000 |
| Active users | 50 |
| Steady query rate | 2 requests/second |
| Burst query rate | 8 requests/second |

The generated load corpus must reproduce document-size, language, category, permission, and freshness distributions. A small functional fixture cannot establish this capacity claim.

## Service objectives

| Workflow | p95 objective |
|---|---:|
| Search | 1.5 s |
| Product compare/reference price | 2.0 s |
| Operational analytics | 4.0 s |
| Grounded Q&A | 4.0 s |
| Listing text checks | 3.0 s |
| Listing image checks | 5.0 s |
| Sourcing advisory | 5.0 s |
| Draft generation | 20 s to accepted background job |
| Review action | 1.0 s |

Measure end-to-end latency at the client boundary. Report p50, p95, p99, error rate, timeout rate, queue delay, model time, database time, reranker time, and cost per successful workflow. The representative mix includes concurrent ingestion, search, Q&A, analytics, review, and export.

## Backpressure and degradation

Bound queues by workflow and workspace. Reserve capacity for interactive requests, cap batch concurrency, enforce payload and result limits, and reject overload with a retryable response before exhausting shared resources. Circuit breakers isolate model, object-store, and integration failures.

If a nonessential model enhancement is unavailable, the workflow may return a clearly labeled deterministic result only when that behavior has its own evaluation. It never silently removes authorization, evidence verification, or approval.

## Cost controls

- cache authorized retrieval candidates and deterministic query results with policy-aware keys
- batch embeddings and background inference
- cap candidates, context, output tokens, retries, and image resolution by workflow
- reuse immutable derived artifacts by content and configuration hash
- track storage, model, database, queue, and egress cost per workflow and workspace
- alert on daily budget variance and block releases projected to raise cost by more than 10% without review

## Observability and alerts

Every request and job carries a correlation ID. Metrics cover traffic, latency, errors, saturation, queue age, retry count, index freshness, ingestion failure, abstention, citation failure, authorization denial, approval age, audit-write failure, and cost. Logs are structured and redacted; traces cross API, job, database, retrieval, model, and integration boundaries.

Alert runbooks define owner role, severity, first diagnostic queries, containment, escalation, recovery, and post-incident evidence. Alerts include sustained SLO burn, old queue leases, stale current index, unusual access denials, audit failure, and budget anomaly.

## Recovery exercise

1. Record recovery-point and recovery-time objectives for each store.
2. Back up relational data, object manifests, configuration, and audit data.
3. Recreate infrastructure in an isolated recovery environment.
4. Restore the database and verify policy activation before application access.
5. Restore object metadata and validate checksums.
6. Rebuild indexes from immutable artifacts where possible.
7. Restore or recreate queue state without duplicating completed effects.
8. Run authorization, citation, workflow, and reconciliation smoke tests.
9. Reconcile audit continuity and document any accepted gap.
10. Record actual recovery point/time, failures, owners, and remediation dates.

## Rollout

Promote sequentially through internal, limited pilot, expanded pilot, and serious capacity stages. Each stage has a rollback artifact and observed SLO window. The serious stage requires a 14-day soak with no critical security, data-loss, approval-bypass, or citation-integrity event and an agreed error-budget posture.

Primary rubric links: A-T1-03, A-T2-07, A-T3-13, B-T1-03, B-T2-07/08, B-T3-09, D-T1-01/02, D-T2-03/04/05, D-T3-06/07.
