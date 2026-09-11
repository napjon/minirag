# Principles and Architecture Decisions

Each decision records its rubric link, tradeoff, measurable gate, and reconsideration trigger. Dates are relative to the delivery schedule in `09-ten-week-delivery.md`.

## ADR-001: Bounded workflows over an unrestricted agent loop

- **Rubric**: A-T2-06, A-T2-10, C-T3-10
- **Decision**: expose explicit workflows for search, grounded Q&A, structured analysis, listing checks, sourcing suggestions, and drafting. Each workflow has typed input, allowed tools, maximum steps, timeout, and output schema.
- **Rejected alternative**: a general agent with arbitrary SQL, filesystem, or network tools.
- **Reason**: bounded workflows make authorization, injection resistance, auditability, latency, and evaluation measurable.
- **Cost**: new use cases require an explicit workflow and evaluation slice.
- **Invariant**: the model cannot acquire a permission that the authenticated principal does not have.
- **Gate**: all tool calls appear in the workflow allowlist; adversarial tests produce zero forbidden actions.
- **Evidence**: workflow registry, authorization tests, injection report, audit samples.
- **Owner / dependencies**: application architecture / identity and policy service.
- **Review**: week 6; reconsider only if a new use case cannot be represented safely with bounded steps.

## ADR-002: PostgreSQL plus pgvector for the serious pilot

- **Rubric**: B-T2-04, B-T2-05, B-T3-09
- **Decision**: store metadata, lexical indexes, vectors, versions, and access-policy keys in shared PostgreSQL. Use object storage for binaries and extracted artifacts.
- **Rejected alternative**: operating a separate search cluster from day one.
- **Reason**: the target envelope fits a partitioned PostgreSQL design while preserving transactional version changes and policy filters.
- **Cost**: hybrid ranking and scaling require careful index, partition, and vacuum management.
- **Invariant**: every searchable row carries workspace, source, version, validity, sensitivity, and policy attributes.
- **Gate**: representative mixed load meets the latency targets in `08-operations-and-scale.md` at the target corpus size.
- **Evidence**: load report, query plans, index-size report, failover exercise.
- **Owner / dependencies**: data platform / representative data generator and production-like database.
- **Review**: week 7 and after each 2x corpus increase; reconsider when sustained p95 or operational effort exceeds its budget after tuning.

## ADR-003: Separate evidence retrieval from operational analytics

- **Rubric**: A-T1-02, A-T2-05, C-T3-10
- **Decision**: narrative questions use hybrid retrieval over versioned evidence. Counts, totals, groupings, price comparisons, and time series use typed, parameterized query patterns in the analytics service.
- **Rejected alternative**: embedding operational rows and asking the model to calculate from retrieved snippets.
- **Reason**: exact values require database semantics; narrative answers require traceable evidence spans.
- **Cost**: query patterns and semantic definitions must be maintained.
- **Invariant**: the model never writes or executes SQL.
- **Gate**: exact-result evaluation passes and invalid dimensions or filters are rejected.
- **Evidence**: query catalog, parameterization tests, result reconciliation report.
- **Owner / dependencies**: analytics / governed schema and metric dictionary.
- **Review**: week 6; reconsider when a requested metric lacks a governed definition.

## ADR-004: Pinned multilingual retrieval models in both profiles

- **Rubric**: A-T1-02, A-T2-08, B-T2-04
- **Decision**: use pinned multilingual embedding and reranking models behind internal interfaces. Both hosted and private profiles run approved model artifacts locally to their trust boundary.
- **Rejected alternative**: silently falling back to lexical-only retrieval in the private profile.
- **Reason**: deployment parity must preserve retrieval behavior and bilingual quality.
- **Cost**: model packaging, accelerator sizing, licensing review, and upgrade evaluations.
- **Invariant**: model name, digest, tokenizer, dimension, and preprocessing version are stored with every index build.
- **Gate**: both profiles pass the same retrieval and Q&A slices within the allowed tolerance.
- **Evidence**: artifact manifest, parity report, blocked-egress run.
- **Owner / dependencies**: ML platform / artifact registry and capacity allocation.
- **Review**: before each model upgrade.

## ADR-005: Human approval controls consequential outputs

- **Rubric**: A-T2-10, B-T2-06, C-T1-03
- **Decision**: listing findings, sourcing recommendations, and generated drafts enter a pending review queue. Only authorized reviewers may accept, reject, revise, or publish them.
- **Rejected alternative**: auto-publishing outputs above a confidence score.
- **Reason**: confidence is not authority, and these outputs may affect real decisions.
- **Cost**: reviewer workload and queue latency.
- **Invariant**: every accepted output links to its evidence, model/configuration version, reviewer, timestamp, and revision history.
- **Gate**: zero workflow or API paths bypass approval; stale evidence invalidates pending approval.
- **Evidence**: transition tests, authorization tests, audit chain samples.
- **Owner / dependencies**: product operations / role model and reviewer staffing.
- **Review**: week 6 and after the first two weeks of pilot use.

## ADR-006: Planning scores and runtime acceptance are separate

- **Rubric**: A-T1-03, A-T2-07, D-T3-07
- **Decision**: plan quality may be reviewed from documents, but runtime criteria remain unverified until reproducible evaluations produce stored results.
- **Rejected alternative**: marking a criterion complete because its intended test is described.
- **Reason**: design completeness and observed system behavior are different evidence types.
- **Cost**: release requires dataset governance and repeatable evaluation infrastructure.
- **Invariant**: scorecards link to immutable run artifacts rather than manually entered pass labels.
- **Gate**: release checks reject missing dataset versions, build identifiers, or result artifacts.
- **Evidence**: signed scorecard and machine-readable evaluation output.
- **Owner / dependencies**: quality lead / evaluation runner and artifact storage.
- **Review**: every release candidate.
