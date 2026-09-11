# Capability Designs

All capabilities use the shared authentication, evidence, workflow, review, and audit components. Acceptance numbers below are release gates, not current results.

## 1. Listing oversight

**Flow:** choose a listing or batch, load the applicable rule version, run deterministic text and structure checks, run approved image checks, compare authorized reference data, create explainable findings, and send them to human review.

Finding types cover specification completeness, category fit, image-content consistency, price outliers, and additional-service indicators. Every finding stores rule version, input version, evidence, severity, confidence bucket, and review state. Duplicate runs with the same inputs are idempotent.

**Pilot acceptance:** at least 200 representative cases; report per-class precision, recall, F1, calibration, and reviewer disagreement. Text findings target macro F1 ≥85% and precision ≥90%; the reviewed vision slice targets precision ≥90%. Material findings cannot auto-enforce a decision.

## 2. Sourcing advisory

**Flow:** apply versioned eligibility and prioritization rules to governed product and supplier attributes, explain matched and unmatched criteria, generate alerts and risk-board entries, and request human disposition.

The system distinguishes missing data from a negative rule result and shows the source timestamp. Rule execution is deterministic; the model may summarize evidence but cannot change eligibility. Human operators remain responsible for final action.

**Pilot acceptance:** two isolated pilot workspaces, at least 20 alert triggers, reproducible rule outputs, no cross-workspace exposure, and complete disposition history.

## 3. Product discovery and reference prices

**Flow:** normalize query terms and filters, run policy-filtered structured and hybrid search, normalize units and pack sizes, rank comparable products, and show price observations with geography, effective date, source, and freshness.

Hard constraints such as category, unit compatibility, currency, and required attributes filter before ranking. Missing normalization prevents a misleading comparison. No live marketplace dependency is required for the pilot.

**Pilot acceptance:** three clean categories and at least 50 judged queries; pilot Precision@5 ≥70%, with the serious release gate defined in `07-evaluation-and-release.md`; zero hard-constraint violations; price calculation accuracy ≥98%.

## 4. Operational data assistant

**Flow:** map the request to an allowlisted query pattern, validate dimensions, measures, filters, workspace, date range, and row limit, run a parameterized statement, then render a table, chart, or spreadsheet with source and freshness.

Unsupported groupings and ambiguous metrics are rejected or clarified. All arithmetic comes from typed results. The model cannot execute SQL or Python.

**Pilot acceptance:** five query patterns with 30 cases each; ≥90% exact answers during pilot and ≥98% for serious release; invalid-scope tests produce zero unauthorized rows.

## 5. Evidence Q&A

**Flow:** search three representative topic families, return claim-level citations with exact spans, disclose freshness and conflict, collect feedback, and preserve an auditable run record.

**Pilot acceptance:** 60 answerable questions, 20 per topic, target ≥85% grounded correctness; 20 out-of-scope questions, target ≥95% correct abstention. Serious release uses the larger frozen sets in `07-evaluation-and-release.md`.

## 6. Controlled drafting

**Flow:** select one of two core output types, load a versioned template, retrieve current policy separately from historical examples, populate only supported fields, validate required sections and claims, and place the draft in the review queue.

Historical examples are labeled and cannot override current policy. Editing creates revisions; a source or policy change invalidates stale pending approvals. Publication requires an authorized reviewer.

**Pilot acceptance:** 15 cases reviewed by three people; ≥70% accepted with only minor edits, zero invented mandatory fields, and zero approval bypasses. Serious release expands the set and raises template conformance as defined in `07-evaluation-and-release.md`.

Primary rubric links: A-T1-04, A-T2-05/06/09/10, B-T1-02, B-T2-04/05/06, C-T1-03/04, C-T2-07/08, C-T3-10, D-T1-01/02.
