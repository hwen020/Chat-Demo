#!/bin/sh
# Run inside a disposable PostgreSQL container after applying migrations and seeding fixtures.
set -eu
case "${1:-}" in
  messenger) table=chat_messages ;;
  ai-chat) table=messages ;;
  *) echo "Pass messenger or ai-chat." >&2; exit 2 ;;
esac

source_db="${POSTGRES_DB:?}"
user="${POSTGRES_USER:?}"
restored="chatflow_restore_$$"
dump=$(mktemp)
created=0
cleanup() {
  rm -f "$dump"
  if [ "$created" -eq 1 ]; then dropdb -U "$user" "$restored"; fi
}
trap cleanup EXIT
# Hash fixture rows without printing conversation data.
snapshot="SELECT count(*) || ':' || coalesce(md5(string_agg(to_jsonb(t)::text, ',' ORDER BY seq, to_jsonb(t)::text)), '') FROM $table t"
original=$(psql -X -v ON_ERROR_STOP=1 -U "$user" -d "$source_db" -Atc "$snapshot")
case "$original" in 0:*) echo "Seed the disposable database before testing backups." >&2; exit 1 ;; esac
version=$(psql -X -v ON_ERROR_STOP=1 -U "$user" -d "$source_db" -Atc 'SELECT version_num FROM alembic_version')
pg_dump -Fc -U "$user" -d "$source_db" -f "$dump"
createdb -U "$user" "$restored"
created=1
pg_restore --exit-on-error -U "$user" -d "$restored" "$dump"
[ "$original" = "$(psql -X -v ON_ERROR_STOP=1 -U "$user" -d "$restored" -Atc "$snapshot")" ]
[ "$version" = "$(psql -X -v ON_ERROR_STOP=1 -U "$user" -d "$restored" -Atc 'SELECT version_num FROM alembic_version')" ]
printf '%s backup restore validated (revision %s, %s message rows).\n' "$1" "$version" "${original%%:*}"
