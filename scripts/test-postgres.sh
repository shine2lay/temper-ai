#!/usr/bin/env bash
# A throwaway Postgres for the database tier of the tests.
#
#   scripts/test-postgres.sh up     start it and print its URL
#   scripts/test-postgres.sh url    print the URL (start it if it is not up)
#   scripts/test-postgres.sh down   remove it
#
# Never temper's live database: this container has a name of its own, a port
# of its own, and keeps everything in RAM (tmpfs), so stopping it leaves
# nothing behind. The tests refuse a URL that could be the live one anyway
# (tests/pgtier.py).
set -euo pipefail

NAME="${TEMPER_TEST_PG_NAME:-temper-test-postgres}"
PORT="${TEMPER_TEST_PG_PORT:-5455}"      # live temper is on 5433; this is not that
IMAGE="${TEMPER_TEST_PG_IMAGE:-pgvector/pgvector:pg16}"
DB="temper_ai_test"
URL="postgresql://temper_ai:test@127.0.0.1:${PORT}/${DB}"

up() {
    if [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null || true)" = "true" ]; then
        return 0
    fi
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    docker run -d --name "$NAME" \
        -e POSTGRES_DB="$DB" -e POSTGRES_USER=temper_ai -e POSTGRES_PASSWORD=test \
        -e PGDATA=/var/lib/postgresql/data/pgdata \
        --tmpfs /var/lib/postgresql/data:rw,size=512m \
        -p "127.0.0.1:${PORT}:5432" \
        "$IMAGE" \
        -c fsync=off -c full_page_writes=off -c synchronous_commit=off >/dev/null
    for _ in $(seq 1 60); do
        if docker exec "$NAME" pg_isready -U temper_ai -d "$DB" >/dev/null 2>&1; then
            return 0
        fi
        sleep 0.5
    done
    echo "test postgres did not come up; docker logs $NAME" >&2
    docker logs --tail 30 "$NAME" >&2 || true
    return 1
}

case "${1:-url}" in
    up)   up; echo "$URL" ;;
    url)  up >/dev/null; echo "$URL" ;;
    down) docker rm -f "$NAME" >/dev/null 2>&1 || true ;;
    *)    echo "usage: $0 {up|url|down}" >&2; exit 2 ;;
esac
