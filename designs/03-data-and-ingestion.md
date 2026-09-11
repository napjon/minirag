# Data and Ingestion Design

## Source authority

| Data class | Authoritative representation | RAG use |
|---|---|---|
| Policies, guides, decisions | versioned documents and exact spans | answer and draft evidence |
| Products, suppliers, prices | normalized relational records | filters, comparisons, matching |
| Events and transactions | governed relational views | counts, totals, trends |
| Images | immutable objects plus derived features | visual checks with provenance |
| Human decisions | append-only review revisions | supervision and audit, never hidden ground truth |

Core entities are workspace, principal, role, grant, source, source version, artifact, page, chunk, embedding, product, category, unit, price observation, rule, finding, workflow run, draft, review revision, feedback, and audit event. Tenant and policy keys appear on all derived records so authorization survives denormalization.

## Source lifecycle

```text
received -> quarantined -> extracting -> normalizing -> validating
         -> chunking -> embedding -> staged -> published
any active stage -> retryable_failure -> prior safe stage
any active stage -> terminal_failure
published -> superseded or withdrawn
```

Only `published` versions are eligible for current-answer retrieval. Historical or as-of queries may access superseded versions if policy permits and the answer labels the requested time. Withdrawal removes a version from new retrieval immediately; asynchronous cleanup may follow.

## Stage contracts

| Stage | Required input | Output and checks |
|---|---|---|
| Receive | binary or structured payload, source metadata | checksum, media type, size, source identity, ingestion ID |
| Quarantine | received artifact | malware result, converter allowlist, safe storage location |
| Extract | validated artifact | page-level text/layout, tables, images, OCR confidence, warnings |
| Normalize | extracted representation | canonical Unicode, headings, lists, tables, stable element IDs |
| Validate | normalized content | page coverage, corruption checks, language, required metadata |
| Chunk | validated elements | bounded semantic chunks with page and element lineage |
| Embed | chunk set and pinned model | vectors plus model digest, tokenizer, dimension, preprocessing version |
| Stage | complete version | searchable index candidate and validation report |
| Publish | approved staged version | atomic current-version pointer and audit event |

Each stage is idempotent by `(source_version_id, stage, configuration_hash)`. A configuration change creates a new derived artifact rather than mutating prior evidence.

## Parsing and quality routing

Native text and layout extraction is preferred. OCR runs for image-only or low-text pages. Tables retain row, column, header, and page references. Parsing confidence routes low-quality pages to review; it never silently discards them. Password-protected, corrupt, unsupported, or suspicious files end in an explicit state with a user-visible reason.

A representative extraction benchmark contains digital text, scans, mixed pages, tables, multi-column layouts, rotated pages, and both supported languages. It measures page coverage, character accuracy, reading order, table-cell recovery, and locator accuracy.

## Chunking

- Start with 450–700 tokens, with a hard ceiling of 900.
- Split first on document structure, then paragraph and sentence boundaries.
- Use at most 80 tokens of overlap and never cross access-policy or version boundaries.
- Keep headings and table headers with dependent content.
- Store exact character offsets into immutable extracted text.
- Attach source version, page, element, language, valid-from/to, sensitivity, and policy attributes.
- Deduplicate by normalized content hash while retaining every authorized provenance edge.

Chunk-size and overlap choices are selected by ablation, not by convention. The winning configuration must improve the frozen retrieval set without breaching storage and latency budgets.

## Version and publication behavior

Publication uses a blue/green index generation and atomically switches the current pointer after completeness checks. Overlapping validity intervals for the same source are rejected. Current queries cannot return superseded content. As-of queries return the version valid at the requested time and label it. Conflicting active sources are both surfaced with authority and effective-date metadata.

## Closeout evidence

- corpus manifest and source coverage report
- extraction benchmark results by document type and language
- stage retry, cancellation, corruption, and idempotency tests
- chunk lineage samples that resolve to exact pages and spans
- version publication, withdrawal, overlap, and rollback tests
- embedding artifact manifest and index completeness report

Primary rubric links: A-T1-01/02/04, A-T2-08/09, B-T2-04/05, B-T3-09, C-T1-04, C-T2-05.
