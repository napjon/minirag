# Agent instructions

## Test

```bash
uv run pytest
uv run python evals/runner.py
```

## Ports

API **8130**, web **3130**. Never 3000 or 8000.

## Module boundaries

Feature modules (`workflows`, `retrieval`, `catalog`, `detection`, `drafting`, `ingestion`, `integrations`) must not bypass `backend/auth/security.py`.

Operational SQL goes only through `backend/analytics/service.py` parameterized statements. Do not add string-built SQL or a Python/SQL tool for the model.

## Data

This repository is fictional. Never commit original TOR/PDF files, extracted source text, screenshots of source material, or a mapping back to supplied documents.

## Do not

Do not create or derive `CLAUDE.md`.
