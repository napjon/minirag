# Operator guide

Rationale and envelope: [architecture.md](architecture.md) §8–9. Commands below match this repository.

Never bind **3000** or **8000**.

## Ports

| Service | Port |
|---|---|
| API (`uv run marketdesk`) | **8130** |
| Web (`cd web && bun run dev`) | **3130** |
| Shared PostgreSQL 16 + pgvector | 5432 |
| Shared Redis | 6379 |
| MinIO S3 | 59000 (console 59001) |
| Private vLLM (optional) | 18000 |

Postgres and Redis are supplied by the shared `devs/infra` stack. This project compose file only starts MinIO object storage; it must not start a second database or queue.

A host-run API cannot use Compose DNS (`http://vllm:18000`). Join the API to the compose network, or set `PRIVATE_MODEL_BASE_URL` to a published port that is not 3000 or 8000. The private profile does not fall back to hosted generation.

## Bring-up

```bash
(cd ../infra && docker compose up -d)
docker compose up -d
cp .env.example .env
uv sync --extra dev
uv run marketdesk-seed
uv run marketdesk
```

Health: `GET http://127.0.0.1:8130/health` → `ok`, `profile`, `provider`, `egress_blocked`. Restore and load-capture commands are in the sections below.

Web (`web/`, Vite **3130**, proxies `/v1` and `/health` to 8130):

```bash
cd web && bun install && bun run dev
```

CORS allows `http://127.0.0.1:3130` and `http://localhost:3130`.

Optional MCP:

```bash
uv sync --extra mcp
export MARKETDESK_API=http://127.0.0.1:8130
export MARKETDESK_TOKEN=...   # from demo login
uv run marketdesk-mcp
```

Draft jobs run inline by default (`JOB_EXECUTION_MODE=inline`) for a single-process demo. Set
`JOB_EXECUTION_MODE=worker` on the API and run `uv run marketdesk-worker` as a separate process to
use PostgreSQL-backed claiming. The worker uses `DATABASE_ADMIN_URL` to discover tenant jobs,
atomically claims rows with `SKIP LOCKED`, retries failed or expired jobs up to
`JOB_MAX_ATTEMPTS`, and rechecks the caller's current membership and permission fingerprint before
generation. Upload ingestion remains inline because the uploaded bytes are request-scoped; moving
uploads to the worker requires staging them in object storage first.

Private profile never falls back to hosted generation (`backend/model_gateway/base.py`).

Tests: `uv run pytest`. Eval CLI: `uv run python evals/runner.py` (writes `evals/last-run.json`). Evaluation CLI: `uv run python evals/runner.py` (writes `evals/last-run.json`, no extra port). MCP tool list: [mcp.md](mcp.md).

For the complete repository check, run `scripts/verify.sh` with
`MARKETDESK_VERIFY_DATABASE_URL` pointing to an isolated database whose name contains
`_test`. The script refuses the ordinary development database; CI provisions a disposable
verification database and runs the same command.

## Environment

Copy `.env.example`. Important keys:

| Variable | Default | Meaning |
|---|---|---|
| `API_PORT` | `8130` | API bind |
| `WEB_ORIGIN` | `http://127.0.0.1:3130` | CORS |
| `AUTH_MODE` | `demo` | Demo JWT; do not use in a shared deployment |
| `JWT_SECRET` | `change-me-local-only` | Must change if demo auth is on |
| `DEPLOYMENT_PROFILE` | `hosted` | `hosted` or `private` |
| `MODEL_PROVIDER` | `fixture` | `fixture` \| `hosted` \| `private` |
| `HOSTED_MODEL_BASE_URL` | `https://hosted-model.example.invalid/v1` | OpenAI-compatible hosted endpoint |
| `HOSTED_MODEL_API_KEY` | empty | Required when provider is `hosted` (no silent fallback) |
| `HOSTED_GENERATION_MODEL` | `hosted-generation-v1` | |
| `PRIVATE_MODEL_BASE_URL` | `http://127.0.0.1:18000/v1` | vLLM-compatible |
| `PRIVATE_GENERATION_MODEL` | `private-generation-32b` | |
| `PRIVATE_EGRESS_BLOCKED` | `false` | When `true` with profile `private`, hosted provider is forbidden |
| `MAX_UPLOAD_BYTES` | `25000000` | Maximum upload payload read by the ingestion job |
| `EMBEDDING_PROVIDER` | `fixture` | `multilingual` is **planned** |

See [model-card.md](model-card.md).

## Seed and demo users

`uv run marketdesk-seed` is idempotent: if workspace slug `harbor` exists, it returns without changes.

Workspace: `harbor`. Demo login:

```bash
curl -s http://127.0.0.1:8130/v1/auth/demo \
  -H 'content-type: application/json' \
  -d '{"email":"analyst@marketdesk.test","workspace":"harbor"}'
```

| Email | Roles | Groups | Can |
|---|---|---|---|
| `admin@marketdesk.test` | admin | ops | everything including audit export |
| `analyst@marketdesk.test` | analyst, viewer | ops | Q&A, analytics, sourcing, price references |
| `reviewer@marketdesk.test` | reviewer, viewer | ops | review drafts, listing/sourcing |
| `drafter@marketdesk.test` | drafter, viewer | ops | create drafts; cannot self-approve |
| `catalog@marketdesk.test` | catalog_editor, viewer | ops | listing checks, catalog |
| `restricted@marketdesk.test` | viewer | restricted | Q&A/search only; not restricted notes, not analytics |

To rebuild seed data: `docker compose down -v` then compose/seed again. Do not re-seed on top of a restore.

## Backup and restore

Search projections live in PostgreSQL (tsvector + pgvector), so a database dump restores retrieval. Object originals are the MinIO volume. Shared Postgres is on host port **5432**. Do not re-seed on top of a restore.

Runnable dump / isolated restore / failover (custom-format `pg_dump` via the shared Postgres container):

```bash
(cd ../infra && docker compose up -d)
scripts/restore.sh dump /tmp/marketdesk.dump
scripts/restore.sh restore /tmp/marketdesk.dump
scripts/restore.sh failover
```

`restore` and `failover` load into isolated database `marketdesk_restore` on the same shared instance. They do not replace live `marketdesk` unless `MARKETDESK_RESTORE_PRIMARY=1` and the restore target is `marketdesk`. After a failover exercise, confirm the isolated database is queryable; for a real cutover, repoint `DATABASE_URL` (still port 5432). Copy or snapshot MinIO volume `marketdesk_minio` with the database.

Manual equivalent:

```bash
(cd ../infra && docker exec -i shareddb-postgres-1 pg_dump -U marketdesk -Fc marketdesk) > /tmp/marketdesk.dump
(cd ../infra && docker exec shareddb-postgres-1 createdb -U postgres -O marketdesk marketdesk_restore)
(cd ../infra && docker exec -i shareddb-postgres-1 pg_restore -U marketdesk -d marketdesk_restore --no-owner --no-acl) < /tmp/marketdesk.dump
```

After restore, confirm `/health`, demo login, and one Q&A against a known published procedure.

Planning targets (not measured here): RPO ≤15 minutes, RTO ≤2 hours. A production restore test must include database, object metadata, memberships/permissions, model/provider settings, and search availability — not only `pg_dump`. Use expand/backfill/validate/contract migrations; treat the search index as rebuildable.

Backup retention in the architecture plan: 35 days. Implement expiry explicitly when backups exist.

## Load capture

`scripts/load_capture.py` is a client. It does not start an API and does not bind 3000 or 8000. It logs in as `analyst@marketdesk.test` and runs a mixed concurrent workload across `/health`, `/v1/questions`, `/v1/products/search`, and `/v1/analytics/queries`, recording p50/p95 latency, errors, elapsed time, and achieved QPS.

Default `MARKETDESK_API` is `http://127.0.0.1:8130`. Point it at a live process:

```bash
uv run marketdesk   # 8130 unless API_PORT is set
MARKETDESK_API=http://127.0.0.1:8130 uv run python scripts/load_capture.py --n 20
```

This is a live-API latency sample, not a 100,000-document ingest.

## Failure behavior

| Failure | Product behavior | Current code |
|---|---|---|
| Search / DB unavailable | Source-backed answers temporarily unavailable | Request errors |
| Generator unavailable | Offer authorized hits without a generated answer | Request errors (no partial-hit path yet) |
| Operational data stale | Show freshness; block if current values are required | Returns `freshness` as the query `end_date` |
| Price feed stale (>72h) | Historical rows with warning; no current recommendation | **implemented** (`insufficient_comparables` / warning) |
| Parser failure | Leave unpublished; repair task | Fast-path ingest; failed parse **planned** |
| Audit persist unavailable | Do not return an unaudited success | Q&A writes `interactions` in the same commit |
| Permission revoked before a draft job starts | Reject execution and record the terminal outcome | Worker reloads membership and compares its permission fingerprint |
| Review service failure | Keep draft; export stays blocked | Export still requires `approved` |
| Interactive overload | Bound queue 200; 429 + `Retry-After`; expire start >15s | Settings exist; enqueue limiter **planned** |
| Hosted key missing | Fail closed | **implemented** |
| Private + egress blocked + hosted provider | Fail closed; never silent hosted fallback | **implemented** |

Do not stream unverified prose as an authoritative answer.

Standing alerts (plan): unauthorized candidate surviving recheck, revision mismatch, missing final audit state, indexing lag, unapproved export attempts, any egress in the private profile. Prometheus counters exist in `backend/observability`; wire them in deployment.
