# Evaluation and Release Design

## Scorecard separation

The planning scorecard evaluates whether scope, architecture, delivery, risk, and evidence requirements are explicit. The runtime scorecard evaluates an immutable build against versioned datasets. A strong plan does not satisfy a runtime gate.

Each dataset manifest records item IDs, provenance category, language, source/version window, permission class, annotation guide, annotator roles, adjudication state, split, exclusions, and content hash. No evaluation item may contain identifying source material.

## Serious-release gates

| Gate | Minimum set | Pass threshold |
|---|---:|---|
| Retrieval | 600 judged queries | Recall@20 ≥95%; no critical slice below 90% |
| Grounded Q&A | same retrieval set | grounded correctness ≥92%; no critical slice below 90% |
| Citations | answerable Q&A set | precision ≥98%; claim coverage ≥95% |
| Abstention | 400 unanswerable/conflict cases | correct abstention ≥99%; over-refusal on answerable set ≤8% |
| Operational analytics | 360 valid and 60 invalid cases per governed pattern family | exact result ≥98%; all invalid or unauthorized requests rejected |
| Analytics scope | 200 adversarial cases | zero unapproved rows or dimensions |
| Product discovery | 400 queries across at least 80/category | Precision@5 ≥80%; zero hard-constraint violations |
| Product matching | 500 pairs | precision ≥98%; recall reported by category |
| Reference prices | 200 normalized cases | calculation accuracy ≥98% |
| Listing text checks | 2,000 labeled cases | macro F1 ≥85%; precision ≥90% |
| Listing image checks | governed review slice | precision ≥90%; recall and calibration reported |
| Sourcing rules | 300 cases | exact rule output; no unexplained state |
| Drafting | 100 cases across both types, at least 25/type | template conformance ≥85%; zero invented mandatory fields |
| Approval | all consequential workflows | zero bypass paths |
| Authorization | at least 1,000 adversarial requests | zero cross-workspace or cross-role exposure |
| Injection | at least 300 direct and indirect cases | zero forbidden actions or protected-data disclosure |
| Audit durability | all accepted, rejected, failed, and cancelled workflow types | required final/failure event always durable |
| Private profile | full critical suite with egress blocked | behavioral parity within approved tolerance; zero external call attempts |

Thresholds can be tightened through change control. Lowering one requires documented risk acceptance and cannot be hidden by an aggregate score.

## Pilot and serious release

The pilot may use the smaller acceptance sets in `05-capability-designs.md` to learn safely with limited users and data. It still requires authentication, policy enforcement, citation integrity, approval controls, audit durability, and isolation gates. Promotion to the serious capacity envelope requires every tabled gate and the load, recovery, and soak gates.

## Evaluation execution

1. Freeze the build, prompts, model digests, index generation, feature flags, and dataset manifests.
2. Start from a clean test namespace and deterministic seed where applicable.
3. Run unit and component checks, then offline quality, security, workflow, and load suites.
4. Store machine-readable per-case results, aggregate and slice metrics, logs, and environment metadata.
5. Have the named evaluator review failures and borderline slices.
6. Require an independent release reviewer to sign the scorecard.
7. Link the signed scorecard to the promoted artifact.

Human evaluation uses a concealed reference answer and standardized rubric. Multiple reviewers independently score the drafting sample; disagreement and adjudication are reported. Annotators cannot score cases they authored without independent review.

## Change control

Retrieval model, chunking, prompt, rules, schema, template, policy logic, or deployment-profile changes trigger the affected evaluation slices. Authorization, injection, approval, citation, audit, and rollback gates always run for a release candidate. A projected per-query or monthly infrastructure-cost increase above 10% blocks promotion until reviewed.

## Closeout record

```text
criterion_id:
status: verified | failed | waived
build_id:
configuration_hash:
dataset_version:
environment:
command_or_job_id:
result_artifact:
observed_value:
threshold:
owner_role:
reviewer_role:
reviewed_at:
exception_and_expiry:
```

Primary rubric links: all runtime criteria, especially A-T1-03/04, A-T2-07, B-T1-01/02/03, B-T2-04/06, C-T1-03/04, C-T2-07, D-T3-07.
