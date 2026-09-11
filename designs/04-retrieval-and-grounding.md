# Retrieval and Grounding Design

## Query sequence

1. Authenticate the principal and validate the workflow request.
2. Resolve workspace, object, sensitivity, locale, and time-policy constraints.
3. Classify the request as evidence retrieval, typed analytics, or a bounded combination.
4. Normalize the query while preserving quoted terms, identifiers, numbers, and dates.
5. Produce lexical and semantic candidates with policy filters applied inside each query.
6. Fuse independent rank lists with reciprocal-rank fusion.
7. Rerank only the authorized candidate pool with the pinned multilingual reranker.
8. Expand adjacent chunks only when they share source, version, section, and policy.
9. Select a diverse evidence set and resolve exact supporting spans.
10. Generate structured claims linked to evidence IDs.
11. Verify semantic support plus deterministic numbers, dates, currencies, and units.
12. Rebuild the answer from supported claims; allow one constrained repair pass.
13. Return the grounded answer or an explicit abstention, then write the audit event.

Lexical ranking uses language-aware full-text indexes and a documented ranking function. Vector search uses approximate indexes tuned against an exact-search sample. Fusion and reranking parameters are configuration-versioned.

## Citation contract

Every citation contains:

```text
source_id
source_version_id
title
page_or_record_locator
element_id
start_offset
end_offset
exact_supporting_span
valid_from / valid_to
retrieved_at
authorized_viewer_url
```

The viewer URL is issued only after a new authorization check. The displayed quote is regenerated from the immutable extracted artifact using its offsets; it is not copied from model output.

## Claim verification

Generation returns a typed list of claims with evidence IDs and answer placement. A semantic verifier classifies each claim as supported, contradicted, or not established. Deterministic validators require all numbers, dates, currencies, percentages, and units to match cited spans or typed analytics results. The final renderer includes only supported claims.

One repair attempt may remove or narrow unsupported claims. If required claims remain unsupported, the workflow abstains. Verification thresholds, prompt versions, and models are stored with the run.

## Conflict, freshness, and abstention

The system abstains when no authorized evidence meets threshold, evidence is stale for the workflow, sources conflict without an authority rule, a requested aggregation is unavailable, or the question is outside the supported domain. Conflict responses present each supported position with version and effective date and avoid selecting a winner unless a configured authority rule resolves it.

Low evidence confidence is shown as a bounded status such as `insufficient evidence`; internal model probabilities are not presented as factual confidence.

## Bilingual behavior

Query language and answer language are detected independently. Retrieval searches both the original query and a controlled translated variant when this improves recall. Citations preserve the source language. A translation is labeled and never replaces the exact source span. Named entities, identifiers, numbers, and units are protected during translation.

## Required ablations

The frozen retrieval set compares lexical-only, vector-only, hybrid fusion, hybrid plus reranking, alternative chunk sizes, query translation, and adjacent-context expansion. Record Recall@20, nDCG@10, MRR, citation precision/coverage, p50/p95 latency, index size, and estimated query cost. Choose a configuration only after slice results by language, source type, age, and permission class are reviewed.

Primary rubric links: A-T1-02/03, A-T2-07/08, B-T1-01/03, B-T2-04/05/06, C-T2-05/07, D-T2-04.
