# Evaluation rubric

Two scorecards stay separate:

1. **Planning / decision quality** — 44 fieldbook items (this page, from [architecture.md](architecture.md) §7).
2. **Observed system behavior** — executable gates (architecture §6, restated below) plus tests in `tests/` and `evals/`.

**Planning scores are not acceptance.** A criterion scored 4 records that a decision is well argued. It does not mean the running system passed the corresponding gate. A demonstration, a green unit suite, or a high rubric total is not a release.

Item identifiers match architecture.md §7.

## Common scoring (planning only)

| Score | Meaning |
|---|---|
| 0 | No committed decision, unsupported assertion, or a technology list without reasoning |
| 2 | Defensible choice with the principal cost or limitation identified |
| 4 | Committed choice, a credible alternative, evidence, and an observable reconsideration trigger |

Intermediate scores are allowed. Missing required evidence caps a decision at 2. Inconsistent assumptions reduce the later item’s score.

Use Tier 1 for bounded initial decisions, Tier 2 for production tradeoffs, and Tier 3 for adaptation after contrary evidence.

Close-out records live in [decisions.md](decisions.md). Allowed statuses: `planned`, `implemented_unverified`, `verified`, `blocked`. `not_applicable` needs a reason and a trigger.

---

## A. AI application engineering — 14 criteria

| ID | Project-specific criterion | Required evidence |
|---|---|---|
| A-T1-01 | Choose native PDF extraction, OCR, or vision processing based on document quality and cost. | Comparison for short documents, long documents, and scanned tables, with measured processing cost and failure modes. |
| A-T1-02 | Assign each source to retrieval, a typed tool, or exclusion according to authority, freshness, and permissions. | Source-mechanism matrix in [source-authority.md](source-authority.md), verified against fixtures. |
| A-T1-03 | Build a small first evaluation that can fail for a concrete defect. | Labeled fixtures, assertions, thresholds, and an intentionally broken implementation that fails. |
| A-T1-04 | Justify supervised listing classifiers using label quality and stable categories. | Label audit, temporal holdout, leakage analysis, and comparison with prompting. |
| A-T2-05 | Enforce access below model-generated arguments. | Endpoint signatures, database roles, and a reachable/blocked resource matrix. |
| A-T2-06 | Prevent retrieved instructions from enabling forbidden actions. | Tool inventory, execution boundaries, and adversarial capability-reachability tests. |
| A-T2-07 | Define exactly what “wrong” means for each capability. | Sampling frame, grading rubric, exclusions, reviewer effort, and disagreement handling. |
| A-T2-08 | Set input, output, retry, and escalation budgets before model execution. | Per-workflow token arithmetic and an observable routing policy. |
| A-T2-09 | Make an unauthorized retrieval or stale answer reconstructable. | Trace fields, source revisions, retention policy, and a detector query. |
| A-T2-10 | Choose fixed workflows and isolate any bounded discretionary step. | Ordered execution sequence, iteration limits, and terminal failure behavior. |
| A-T3-11 | Diagnose whether disappointing results arise from retrieval, generation, product design, or unrealistic goals. | Stratified trace review, user-edit analysis, and a remediation branch for each finding. |
| A-T3-12 | Prevent prompt changes from silently increasing cost or reducing quality. | Versioned prompts, paired evaluations, merge gates, and an audited override mechanism. |
| A-T3-13 | Optimize the stage actually responsible for latency. | Stage timings, ranked interventions, and quality checks attached to each experiment. |
| A-T3-14 | Choose retraining, prompt changes, escalation, or abstention from observed error patterns. | Independently labeled holdout and error distribution, including rare cases. |

## B. Software engineering — 11 criteria

| ID | Project-specific criterion | Required evidence |
|---|---|---|
| B-T1-01 | Make uploads and jobs survive disconnection, refresh, and process failure. | State machine, idempotency behavior, and restart/replay tests. |
| B-T1-02 | Store operational results, revisions, evidence, and feedback with appropriate lifetimes. | Entity model, indexes, access patterns, and retention schedule. |
| B-T1-03 | Keep production credentials outside developer and coding-agent environments. | Credential provisioning/rotation process and network-access verification. |
| B-T2-04 | Select the smallest architecture that satisfies the chosen scale and private profile. | Component diagram and deferred components with measurable introduction triggers. |
| B-T2-05 | Compare colocated vectors, dedicated search, and lexical-only retrieval. | Operational cost, consistency, recall, and workload benchmark comparison. |
| B-T2-06 | Design useful waiting, navigation, retry, cancellation, and failure states. | UI state table linked to durable backend job states. |
| B-T2-07 | Bound parser and renderer execution by network, filesystem, credentials, and resources. | Containment configuration and tests that attempt prohibited access. |
| B-T2-08 | Size concurrency and define visible behavior during throttling. | Arrival-rate arithmetic, bounded queues, and overload tests. |
| B-T3-09 | Reassess component boundaries when deployment independence or scaling fails. | Dependency measurements and explicit keep/split/recombine criteria. |
| B-T3-10 | Change schemas and search generations without losing permissions or evidence. | Expand/backfill/validate/switch/retire sequence with reconciliation checks. |
| B-T3-11 | Prevent test growth from making verification impractical. | Test-duration profile, duplication analysis, and a CI runtime budget. |

## C. Coding-agent workflow — 12 criteria

| ID | Project-specific criterion | Required evidence |
|---|---|---|
| C-T1-01 | Specify expensive-to-change contracts before implementation while leaving cosmetic details flexible. | Bounded implementation briefs and a list of deliberately deferred details. |
| C-T1-02 | Make source authority, authorization, and workflow boundaries discoverable. | Concise module map and entry-point documentation. |
| C-T1-03 | Review behavior and consequential boundaries before presentation details. | Review sequence prioritizing access, writes, exports, and source correctness. |
| C-T1-04 | Keep standing repository guidance short, actionable, and maintained. | Proposed instruction content, explicit exclusions, and an owner role. |
| C-T2-05 | Decompose work into independently verifiable changes. | Task dependency map and a closing test for every work package. |
| C-T2-06 | Enforce coding-agent permissions through the environment. | Allowed operations, human-controlled operations, and unreachable production resources. |
| C-T2-07 | Allocate review attention with mechanical risk classification. | Rules based on security paths, migrations, model changes, and periodic sampling. |
| C-T2-08 | Separate implementation from independent security verification. | Ownership split and adversarial cases produced outside the implementation work. |
| C-T2-09 | Turn recurring mistakes into enforceable checks. | Chosen lint, contract test, or authorization property, with its placement in the development loop. |
| C-T3-10 | Detect work that passes tests while violating architectural intent. | Dependency checks forbidding bypasses of authorization and typed query services. |
| C-T3-11 | Use parallel coding agents only when integration work remains manageable. | Isolation and merge protocol, shared decision record, and a measured stop condition. |
| C-T3-12 | Test invariants beyond the attack examples already known. | Independently generated attacks, capability restrictions, and production detection. |

C-T3-11 does not itself authorize parallel agents. Delegation is a separate execution decision.

## D. Product and delivery judgment — 7 criteria

| ID | Project-specific criterion | Required evidence |
|---|---|---|
| D-T1-01 | Test whether users’ tasks are answerable from available data and whether assistance saves time. | Falsifiable assumptions and short task-observation studies. |
| D-T1-02 | Make demonstrations real where uncertainty matters. | Real-versus-simulated inventory and the hypothesis each demonstration tests. |
| D-T2-03 | Evaluate cost relative to completed useful work and control unexplained increases. | Cost per accepted answer/draft and comparison with measured user effort. |
| D-T2-04 | Treat unexpected usage as both a risk signal and a possible product need. | Usage observation, immediate mitigation, and a small validation experiment. |
| D-T2-05 | Decide what to build, adopt, and defer when usage expands. | Build/adopt/defer table protecting evidence quality and the user-feedback loop. |
| D-T3-06 | Recommend continuation, redirection, or stopping using separate value, quality, and risk decisions. | Decision memo with measurable continuation and stop conditions. |
| D-T3-07 | Attach important measurements to workflows the team already performs. | Owned merge/release/incident checks and indicators that the practice is deteriorating. |

---

## Executable system gates (acceptance)

These gates evaluate **behavior**, not write-ups. Synthetic data is suitable for contracts and controlled failures; it cannot establish real-world detection quality. Production acceptance needs representative authorized data.

Per-answer correctness: right conclusion, relevant conditions, no material unsupported claim, and correct supporting sources. Citations alone do not pass.

| Area | Test population | Release gate |
|---|---|---|
| Retrieval | 600 answerable questions across topics and languages | Evidence Recall@20 ≥95%; report each language/topic slice |
| Policy Q&A | Same 600 cases, human adjudicated | Correct and adequately supported answers ≥92% overall; ≥90% per major slice |
| Citations | Claims and citations from Q&A set | Citation support precision ≥98%; citation coverage ≥95% |
| Abstention | 400 unsupported, missing-evidence, and conflicting-source cases | Correct abstention/clarification ≥99%; answerable-question over-refusal ≤8% |
| Analytics | 360 cases, 60 per pattern | Result correctness ≥98%; every returned numeric fact matches the query result |
| Analytics scope | 200 unsupported or malformed requests | No unapproved query execution |
| Discovery | 400 queries, 80 per category | Precision@5 ≥80% in every category; hard-constraint violation count = 0 |
| Product matching | 500 labeled pairs, including difficult variants | “Same product” precision ≥98%; recall reported separately |
| Reference prices | 200 comparability cases | Correct normalization and provenance in ≥98%; insufficient-data rules pass every boundary test |
| Listing detectors | ≥2,000 adjudicated cases, plus frozen holdout | Macro-F1 ≥85%; per-check precision ≥90%; report recall, abstention, and false positives |
| Vision checks | Dedicated image slice within detector set | Precision ≥90%; unsupported visual claims count toward failures |
| Sourcing rules | 300 executable event fixtures | Exact rule outcomes match all fixtures; every finding links to its rule and evidence |
| Draft usefulness | 100 briefs, 25 per template | ≥85% judged usable starting points; no invented mandatory factual values |
| Draft approval | State, concurrency, export, and replay tests | Zero application-path approval bypasses |
| Authorization | ≥1,000 role/resource/action combinations plus property tests | Zero unauthorized content exposure |
| Injection | ≥300 independently authored adversarial cases | Zero forbidden capability execution or unauthorized data delivery |
| Audit completeness | Reconciliation against accepted requests/jobs | Every accepted interaction has a durable final or explicit failure state |
| Private deployment | Full integration test with Internet egress blocked | All supported workflows operate; no external fallback |

Report confidence intervals and denominators. Do not present “zero failures in the test set” as proof that a failure class is impossible.

A release fails if a hard security invariant fails, a quality gate falls below threshold, or normalized workflow cost rises more than 10% without a reviewed budget change.

## What this repo executes today

`uv run pytest` runs `tests/` and `evals/`.

| Test | Gate it approximates |
|---|---|
| `test_policy_qa_returns_citations` | Citation IDs ⊆ server evidence |
| `test_restricted_source_not_visible_to_viewer` | Authorization slice |
| `test_out_of_scope` | Topic boundary |
| `test_analytics_allowlist_and_numbers` / `test_analytics_rejects_unknown_category` | Analytics scope |
| `test_product_search_hard_filters` | Hard-constraint violation count = 0 (tiny set) |
| `test_listing_and_sourcing_checks` | Detectors run; `GET /v1/findings/{id}` capability split |
| `test_draft_self_approval_blocked_and_export_gate` | Zero approval bypass on this path |
| `test_invented_citation_is_stripped` | Fixture generator emits an invented evidence id |
| `tests/test_authorization.py` | Extra role/resource denials |
| `tests/test_injection.py` | Retrieved-instruction / capability reachability slice |
| `tests/test_catalog_matching.py` | Same/comparable/not-comparable labels |
| `tests/test_sourcing_rules.py` | Deterministic sourcing rule fixtures |
| `evals/test_eval_gates.py` + `evals/cases.json` | Small Q&A status contracts, including `invented_citation` |
| `evals/runner.py` | CLI writes `evals/last-run.json`; exits 1 on failure |
| `test_mcp_contract.py` | MCP tool names match the manifest; approve/SQL/email tools absent |

These are executable contracts, not the §6 populations. Status of the large gates: **planned** unless a close-out in [decisions.md](decisions.md) says `verified`.

For a data-free demonstration, `uv run python scripts/verify_release.py --assume-synthetic`
also writes an explicit 48-item `assumed-closeout.json`. That artifact proves the scorecard
plumbing and demo workflows under generated assumptions; it does not change any ledger item to
`verified` or permit serious-release promotion.
