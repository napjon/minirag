# Rubric Traceability Matrix

This matrix covers every criterion in the plan. “Design response” points to the controlling design. “Closeout evidence” is required before the criterion can be marked verified. Initial status for every row is **Designed; runtime unverified**.

## A — Fit and requirements

| ID | Design response | Required closeout evidence |
|---|---|---|
| A-T1-01 | `03` source lifecycle, parsing, OCR, table preservation | corpus inventory and extraction benchmark |
| A-T1-02 | `03` source authority; `04` bilingual retrieval; `05` typed analytics | source-to-workflow coverage and bilingual slices |
| A-T1-03 | `07` immutable runtime scorecard; `08` measured SLOs | versioned quality, load, and cost reports |
| A-T1-04 | `03` representative document cases; `05` capability datasets | labeled dataset manifests and split audit |
| A-T2-05 | `02` boundaries; `06` layered authorization | cross-role/workspace security report |
| A-T2-06 | `01` bounded workflows; `02` typed tools and jobs | tool allowlist and failure-path tests |
| A-T2-07 | `04` ablations; `07` quality gates; `08` capacity limits | selected configuration report with tradeoffs |
| A-T2-08 | `01` pinned models; `03` embedding manifests | model evaluation, license review, artifact digests |
| A-T2-09 | `02` durable jobs; `03` idempotent ingestion | retry, cancellation, replay, and recovery tests |
| A-T2-10 | `01` human approval; `05` review flows | transition tests and zero-bypass result |
| A-T3-11 | `04` per-stage traces; `05` reviewer edits; `07` sliced results | error attribution and remediation decision record |
| A-T3-12 | `07` versioned prompts, paired evaluations, and audited overrides | before/after quality and cost report plus approval |
| A-T3-13 | `08` stage timings and bottleneck metrics | ranked latency experiments with quality checks |
| A-T3-14 | `04` abstention/repair choices; `07` independent evaluation | holdout error distribution and treatment decision |

## B — Technical design

| ID | Design response | Required closeout evidence |
|---|---|---|
| B-T1-01 | `04` claim verification and citations | grounded Q&A and citation reports |
| B-T1-02 | `05` drafting, findings, review state | human evaluation and approval audit |
| B-T1-03 | `04` conflict/abstention; `08` reliability objectives | abstention, conflict, load, and failure reports |
| B-T2-04 | `01` PostgreSQL/vector choice; `03` chunking; `04` retrieval | retrieval ablation and index/load report |
| B-T2-05 | `02` policy-first sequence; `06` four layers | policy predicate and row-level-policy tests |
| B-T2-06 | `01` approval decision; `05` capability review flows | concurrency, stale approval, and bypass tests |
| B-T2-07 | `06` security/deployment; `08` recovery | threat-model closure and recovery evidence |
| B-T2-08 | `08` arrival envelope, bounded queues, and degradation | arrival-rate model, mixed-load and overload reports |
| B-T3-09 | `02` component ownership; `08` scale observations | dependency measurements and keep/split/recombine ADR |
| B-T3-10 | `03` blue/green publication and version lineage | expand/backfill/validate/switch/retire reconciliation |
| B-T3-11 | `07` selective reruns and release suites; `09` CI gates | test-duration profile, duplication review, CI budget |

## C — Delivery feasibility

| ID | Design response | Required closeout evidence |
|---|---|---|
| C-T1-01 | `09` weekly deliverables and scope control | staffed work breakdown and completed exit records |
| C-T1-02 | `09` review cadence and dependencies | weekly milestone trend and dependency closure |
| C-T1-03 | `05` human reviewer exercises; `07` human evaluation | reviewer agreement, adjudication, acceptance metrics |
| C-T1-04 | `03` extraction benchmark; `07` dataset contract | dataset quality and representativeness report |
| C-T2-05 | `02` component boundaries; `03` stage contracts; `06` profiles | integration and profile tests |
| C-T2-06 | `06` security gates; `08` operational controls | scans, runbooks, alert and failure exercises |
| C-T2-07 | `04` and `05` failure/abstention behavior | negative-path and degraded-mode evaluation |
| C-T2-08 | `06` security ownership; `07` independent release review | independently authored adversarial cases and sign-off |
| C-T2-09 | `02` boundary rules; `07` mandatory gates | lint, contract, and authorization-property checks in CI |
| C-T3-10 | `01` no arbitrary SQL/tools; `02` bounded services | static checks, tool registry, adversarial tests |
| C-T3-11 | `09` weeks 8–10 documentation and support | guide review, training, support handover |
| C-T3-12 | `06` profile parity; `08` recovery/rollout | blocked-egress and isolated restore reports |

## D — Completeness and professionalism

| ID | Design response | Required closeout evidence |
|---|---|---|
| D-T1-01 | `08` measurable service objectives; `09` exit criteria | SLO and milestone result artifacts |
| D-T1-02 | `05` capability acceptance; `07` serious gates | signed pilot and serious-release scorecards |
| D-T2-03 | `06` threat controls; `08` failure operations | security review and incident exercises |
| D-T2-04 | `02` trust boundaries; `04` evidence controls; `06` MCP | injection, leakage, and isolation results |
| D-T2-05 | `01` reconsideration triggers; `08` expansion controls | build/adopt/defer decision table at each scale review |
| D-T3-06 | `06` signed promotion and retention; `08` rollback | release, rollback, backup, and deletion records |
| D-T3-07 | `01` decision format; `07` change control | approved ADRs, exceptions, and reevaluation history |

## Review rule

A weekly review must walk every row affected by that week. The reviewer links artifacts rather than copying conclusions into this file. Failed criteria remain visible with an owner, remediation, target date, and release impact. Aggregate scores cannot conceal a failed zero-tolerance security, approval, audit, isolation, or evidence-integrity gate.

The machine-readable closeout ledger is `release/ledger.json` (44 rubric rows plus four
cross-cutting release gates). `scripts/verify_release.py --assume-synthetic` emits a demo-only
assumption record for all 48 items while preserving the production ledger's open blockers.
