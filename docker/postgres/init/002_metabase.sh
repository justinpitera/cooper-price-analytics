#!/usr/bin/env bash
set -euo pipefail

metabase_database="${MB_DB_DBNAME:-metabase}"
if [ "$metabase_database" = "$POSTGRES_DB" ]; then
    echo 'MB_DB_DBNAME must differ from POSTGRES_DB.' >&2
    exit 1
fi

# Also safe to apply explicitly to an existing PostgreSQL volume.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    --set=metabase_database="$metabase_database" <<'SQL'
SELECT format('CREATE DATABASE %I', :'metabase_database')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'metabase_database')
\gexec
SQL
