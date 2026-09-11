#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -z "${MARKETDESK_VERIFY_DATABASE_URL:-}" ]]; then
  echo "MARKETDESK_VERIFY_DATABASE_URL must point to an isolated verification database." >&2
  exit 2
fi
if [[ "$MARKETDESK_VERIFY_DATABASE_URL" != *"_test"* && "${CI:-}" != "true" ]]; then
  echo "refusing verification database without '_test' in its URL" >&2
  exit 2
fi

export DATABASE_URL="$MARKETDESK_VERIFY_DATABASE_URL"
export DATABASE_ADMIN_URL="${MARKETDESK_VERIFY_DATABASE_ADMIN_URL:-$MARKETDESK_VERIFY_DATABASE_URL}"
export MODEL_PROVIDER=fixture
export AUTH_MODE=demo
export DEPLOYMENT_PROFILE=hosted

uv run ruff check backend tests evals scripts alembic
uv run alembic upgrade head
uv run pytest
uv run python evals/runner.py --output /tmp/minirag-eval-last-run.json

cd web
bun install --frozen-lockfile
bun run lint
bun test src
bun run build
