# Marketdesk

Hypothetical marketplace operations desk: policy Q&A with citations, operational analytics, catalog discovery, listing/sourcing checks, and reviewed document drafting.

This repository is fictional. It does not describe a real organization, contract, or dataset.

## Stack

Python 3.12+, FastAPI, PostgreSQL/pgvector, React/Vite, optional MCP. LangChain is not used.

API listens on **8130**. Web listens on **3130**. Do not use ports 3000 or 8000.

## Local run

```bash
(cd ../infra && docker compose up -d)
docker compose up -d        # MinIO object storage only
cp .env.example .env
uv sync --extra dev
uv run marketdesk-seed
uv run marketdesk
```

In another terminal:

```bash
cd web && bun install && bun run dev
```

Demo users (workspace `harbor`):

- `admin@marketdesk.test`
- `analyst@marketdesk.test`
- `reviewer@marketdesk.test`
- `drafter@marketdesk.test`
- `catalog@marketdesk.test`
- `restricted@marketdesk.test`

Default model provider is `fixture` (deterministic, no network). Hosted generation uses a configured OpenAI-compatible endpoint (`HOSTED_MODEL_API_KEY` / `HOSTED_MODEL_BASE_URL`, model set by `HOSTED_GENERATION_MODEL`). Private generation uses a vLLM-compatible endpoint. There is no silent provider fallback.

```bash
uv run pytest
uv run python evals/runner.py
```

For the complete repository check, point at an isolated database whose name contains
`_test`, then run:

```bash
MARKETDESK_VERIFY_DATABASE_URL=postgresql+asyncpg://user:password@host:5432/minirag_test scripts/verify.sh
```

To generate a reviewable demo scorecard for every rubric row plus the four release
gates when representative data is unavailable, run:

```bash
uv run python scripts/verify_release.py --assume-synthetic
```

This writes `artifacts/release/assumed-closeout.json` with 48 explicit synthetic
assumptions. It keeps the serious production verdict open until representative
quality, security, scale, recovery, private-profile, and soak evidence is attached.

The eval runner writes `evals/last-run.json` (pass/fail per case). MCP adapter: `docs/mcp.md`.

## Documentation

| Doc | Purpose |
|---|---|
| [docs/architecture.md](docs/architecture.md) | System design, envelope, and planning targets |
| [docs/source-authority.md](docs/source-authority.md) | Source types, authority, lifecycle, citations |
| [docs/access-control.md](docs/access-control.md) | Roles, capabilities, RLS, MCP limits |
| [docs/mcp.md](docs/mcp.md) | MCP tools, HTTP mapping, forbidden capabilities |
| [docs/threat-model.md](docs/threat-model.md) | Untrusted content, injection, approval, egress |
| [docs/operator-guide.md](docs/operator-guide.md) | Compose, seed, ports, backup, failure behavior |
| [docs/reviewer-guide.md](docs/reviewer-guide.md) | Draft review, self-approval ban, export gate |
| [docs/model-card.md](docs/model-card.md) | Fixture, hosted endpoint, private inference, embeddings |
| [docs/eval-rubric.md](docs/eval-rubric.md) | 44 planning criteria and executable gates |
| [docs/release-closeout.md](docs/release-closeout.md) | 48-item ledger, synthetic evidence, and release verifier |
| [docs/decisions.md](docs/decisions.md) | Close-out records |
| [AGENTS.md](AGENTS.md) | Test command, module boundaries, data restrictions |
