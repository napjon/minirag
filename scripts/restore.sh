#!/usr/bin/env bash
# Dump and restore the application database on the shared Postgres instance (host port 5432).
#
#   scripts/restore.sh dump [outfile]
#   scripts/restore.sh restore [infile] [target_db]
#   scripts/restore.sh failover [infile]
#
# dump writes a custom-format pg_dump of database `marketdesk`.
# restore loads that dump into an isolated database (default `marketdesk_restore`),
# not the live `marketdesk` database, unless MARKETDESK_RESTORE_PRIMARY=1 and
# target_db is `marketdesk`.
# failover dumps if needed, restores into the isolated database, and verifies
# the copy is queryable. It does not drop live data or re-seed.
#
# Requires: shared Postgres container healthy on 5432. Do not re-seed on top of a restore.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

DUMP_DEFAULT="${MARKETDESK_DUMP_FILE:-/tmp/marketdesk.dump}"
LIVE_DB="${MARKETDESK_LIVE_DB:-marketdesk}"
ISOLATED_DB="${MARKETDESK_RESTORE_DB:-marketdesk_restore}"
PGUSER="${POSTGRES_USER:-marketdesk}"
PGADMIN_USER="${POSTGRES_ADMIN_USER:-postgres}"
CONTAINER="${MARKETDESK_PG_CONTAINER:-shareddb-postgres-1}"

pg() {
  docker exec "$CONTAINER" "$@"
}

pg_admin() {
  docker exec "$CONTAINER" "$@"
}

require_ident() {
  local name="$1"
  if [[ ! "$name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    echo "invalid database or role name: $name" >&2
    exit 1
  fi
}

wait_postgres() {
  local i
  for i in $(seq 1 40); do
    if pg pg_isready -U "$PGADMIN_USER" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "shared postgres container '$CONTAINER' is not ready (host port 5432)." >&2
  echo "Start it with: (cd ../infra && docker compose up -d)" >&2
  exit 1
}

usage() {
  sed -n '2,16p' "$0" | sed 's/^# \?//'
  exit 2
}

restore_db() {
  local infile="$1"
  local target="$2"
  require_ident "$target"
  if [[ ! -f "$infile" ]]; then
    echo "dump file not found: $infile" >&2
    exit 1
  fi
  if [[ "$target" == "$LIVE_DB" && "${MARKETDESK_RESTORE_PRIMARY:-}" != "1" ]]; then
    echo "refusing to restore onto live database '$LIVE_DB'." >&2
    echo "use target '$ISOLATED_DB' or set MARKETDESK_RESTORE_PRIMARY=1" >&2
    exit 1
  fi
  pg_admin psql -U "$PGADMIN_USER" -d postgres -v ON_ERROR_STOP=1 -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${target}' AND pid <> pg_backend_pid();" \
    >/dev/null
  pg_admin dropdb -U "$PGADMIN_USER" --if-exists "$target"
  pg_admin createdb -U "$PGADMIN_USER" -O "$PGUSER" "$target"
  pg pg_restore -U "$PGUSER" -d "$target" --no-owner --no-acl --exit-on-error < "$infile"
}

cmd="${1:-}"
shift || true
require_ident "$LIVE_DB"
require_ident "$ISOLATED_DB"
require_ident "$PGUSER"

case "$cmd" in
  dump)
    outfile="${1:-$DUMP_DEFAULT}"
    wait_postgres
    mkdir -p "$(dirname "$outfile")"
    pg pg_dump -U "$PGUSER" -Fc "$LIVE_DB" > "$outfile"
    echo "dumped $LIVE_DB -> $outfile"
    ;;
  restore)
    infile="${1:-$DUMP_DEFAULT}"
    target="${2:-$ISOLATED_DB}"
    wait_postgres
    restore_db "$infile" "$target"
    echo "restored $infile -> $target"
    echo "dry-run DATABASE_URL: postgresql+asyncpg://${PGUSER}:${PGUSER}@127.0.0.1:5432/${target}"
    ;;
  failover)
    infile="${1:-}"
    wait_postgres
    if [[ -z "$infile" ]]; then
      infile="$DUMP_DEFAULT"
      mkdir -p "$(dirname "$infile")"
      pg pg_dump -U "$PGUSER" -Fc "$LIVE_DB" > "$infile"
      echo "dumped $LIVE_DB -> $infile"
    fi
    restore_db "$infile" "$ISOLATED_DB"
    tables="$(pg psql -U "$PGUSER" -d "$ISOLATED_DB" -Atc \
      "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';" | tr -d '\r')"
    if [[ -z "$tables" || "$tables" -lt 1 ]]; then
      echo "failover verify failed: no public tables in $ISOLATED_DB" >&2
      exit 1
    fi
    echo "failover ok: $ISOLATED_DB public_tables=$tables dump=$infile"
    echo "live database $LIVE_DB was not modified"
    echo "cutover would repoint DATABASE_URL to postgresql+asyncpg://${PGUSER}:${PGUSER}@127.0.0.1:5432/${ISOLATED_DB}"
    echo "do not run marketdesk-seed against a restored database"
    ;;
  *)
    usage
    ;;
esac
