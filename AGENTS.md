# Agent instructions

## Test

```bash
uv run pytest
uv run python evals/runner.py
```

`./run.sh test` runs both, plus lint, on the `fixture` provider (no model needed).

## Ports

The API and the pages share port **8130**. 3130 stays reserved for a separate web app. Never 3000 or 8000.

## Boundaries

- Local only. No hosted model APIs and no cloud services: models run through Ollama on localhost, or the `fixture` provider.
- No silent provider fallback. `PROVIDER` decides; if Ollama is down the trace records an error.
- Every answer path goes through `Engine.answer` in `minirag/pipeline.py`, so it is ground-checked, traced and written to the audit log before it is returned.
- SQL lives only in `minirag/store.py` and is always parameterized.

## Data

This repository is fictional: the bank, its policies and the golden set are invented. Never commit real documents, extracted source text, screenshots of source material, or a mapping back to supplied documents.

When a corpus file changes, update `evals/golden.json` in the same commit (a test checks that every `evidence` line exists in the corpus).

## Do not

Do not create or derive `CLAUDE.md`.
