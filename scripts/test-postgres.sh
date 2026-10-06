#!/usr/bin/env bash
# The test Postgres for the database tier of the tests.
#
#   scripts/test-postgres.sh up            start it if it is not up, wait until it answers, print its URL
#   scripts/test-postgres.sh url           the same, for "$(...)": only the URL on stdout
#   scripts/test-postgres.sh down          remove it, unless a run is using it
#   scripts/test-postgres.sh down --force  remove it anyway
#
# One container for the whole machine (temper-test-postgres, port 5455), shared
# by every worktree, every chat's pre-commit hook and every run by hand: leave
# it up. Each run keeps to schemas of its own and drops them when it ends
# (tests/pgtier.py), so runs at the same time do not see each other's rows. A
# long or heavy run can have a container of its own: set TEMPER_TEST_PG_NAME
# and TEMPER_TEST_PG_PORT, and `down` it afterwards.
#
# Never temper's live database: this container has a name of its own, a port
# of its own, and keeps everything in RAM (tmpfs), so removing it leaves
# nothing behind. The tests refuse a URL that could be the live one anyway
# (tests/pgtier.py).
set -euo pipefail

NAME="${TEMPER_TEST_PG_NAME:-temper-test-postgres}"
PORT="${TEMPER_TEST_PG_PORT:-5455}"      # live temper is on 5433; this is not that
IMAGE="${TEMPER_TEST_PG_IMAGE:-pgvector/pgvector:pg16}"
DB="temper_ai_test"
URL="postgresql://temper_ai:test@127.0.0.1:${PORT}/${DB}"
LOCK="${XDG_RUNTIME_DIR:-/tmp}/temper-test-postgres-${NAME}.lock"
LOCK_WAIT=120

usage() {
    echo "usage: $0 {up|url|down [--force]}" >&2
    exit 2
}

# One caller at a time per container, from the check to the answer. Without
# it, callers that found no container at the same moment each removed and
# started one: three of four failed with docker's "name already in use"
# (2026-10-04). Released when this script exits.
take_lock() {
    if ! command -v flock >/dev/null; then
        echo "test-postgres.sh: flock is not installed; going on without the lock" >&2
        return 0
    fi
    exec 9>>"$LOCK"
    if ! flock -w "$LOCK_WAIT" 9; then
        echo "test-postgres.sh: another caller has held $LOCK for ${LOCK_WAIT}s; giving up." >&2
        exit 1
    fi
}

running() {
    [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null || true)" = "true" ]
}

psql_in() {
    docker exec "$NAME" psql -U temper_ai -d "$DB" -XAtq -c "$1"
}

start() {
    # size=4g: up to five builds run their suites here at the same time
    # (2026-10-05), each in schemas of its own, and 512 MB was a third full
    # with nothing running. A tmpfs takes RAM only for what it holds, so the
    # cap costs nothing until it is used. max_wal_size: Postgres keeps up to
    # 1 GB of write-ahead log by default; here it stays near 128 MB.
    # max_connections: a run takes up to ~30, and several runs share the
    # container. The label says which of these settings a container has.
    docker run -d --name "$NAME" \
        --label temper.test-pg.version=3 \
        -e POSTGRES_DB="$DB" -e POSTGRES_USER=temper_ai -e POSTGRES_PASSWORD=test \
        -e PGDATA=/var/lib/postgresql/data/pgdata \
        --tmpfs /var/lib/postgresql/data:rw,size=4g \
        -p "127.0.0.1:${PORT}:5432" \
        "$IMAGE" \
        -c fsync=off -c full_page_writes=off -c synchronous_commit=off \
        -c max_wal_size=128MB -c min_wal_size=32MB -c max_connections=300 >/dev/null
}

wait_ready() {
    # Over TCP, inside the container: while the image sets the database up it
    # runs a server on the unix socket only, which answers and then stops.
    for _ in $(seq 1 120); do
        if docker exec "$NAME" pg_isready -h 127.0.0.1 -p 5432 -U temper_ai -d "$DB" >/dev/null 2>&1; then
            return 0
        fi
        sleep 0.5
    done
    echo "test postgres $NAME did not answer within a minute; docker logs $NAME:" >&2
    docker logs --tail 30 "$NAME" >&2 || true
    return 1
}

up() {
    take_lock
    if ! running; then
        # Nobody can be using a container that is not running: one that exists
        # (it stopped, or its start failed) is replaced. A running one never is.
        docker rm -f "$NAME" >/dev/null 2>&1 || true
        start
    fi
    wait_ready
}

pid_alive() {
    # Whoever owns it: kill -0 says "not permitted" for someone else's process.
    [ "$1" -gt 0 ] && { [ -d "/proc/$1" ] || kill -0 "$1" 2>/dev/null; }
}

# Why the container is in use, or nothing when it is free: a client connection
# other than this check, or a schema of a run that is still going
# (tier_p<pid>_<worker>, tests/pgtier.py). A run on SQLite-only tests holds no
# connection for a while, so the schemas are checked too.
in_use() {
    local clients names name pid
    local -a why=() live=()
    if ! clients=$(psql_in "SELECT count(*) FROM pg_stat_activity
                            WHERE backend_type = 'client backend' AND pid <> pg_backend_pid()"); then
        echo "could not ask it whether it is in use"
        return
    fi
    if [ "$clients" != "0" ]; then
        why+=("$clients client connection(s) open")
    fi
    if ! names=$(psql_in "SELECT nspname FROM pg_namespace WHERE nspname ~ '^tier_p[0-9]+_'"); then
        echo "could not list its schemas"
        return
    fi
    for name in $names; do
        pid=${name#tier_p}
        pid=${pid%%_*}
        if pid_alive "$pid"; then
            live+=("$name")
        fi
    done
    if [ ${#live[@]} -gt 0 ]; then
        why+=("schemas of runs still going: ${live[*]}")
    fi
    if [ ${#why[@]} -gt 0 ]; then
        local IFS=";"
        echo "${why[*]}"
    fi
}

down() {
    local force=0 why
    case "${1:-}" in
        "") ;;
        --force) force=1 ;;
        *) usage ;;
    esac
    take_lock
    if ! docker container inspect "$NAME" >/dev/null 2>&1; then
        return 0
    fi
    if [ "$force" = 0 ] && running; then
        why=$(in_use)
        if [ -n "$why" ]; then
            echo "test-postgres.sh: not removing $NAME, it is in use: ${why//;/; }." >&2
            echo "  It is shared by every worktree and hook, so leave it up; 'down --force' removes it anyway." >&2
            exit 1
        fi
    fi
    docker rm -f "$NAME" >/dev/null
}

case "${1:-url}" in
    up)   [ $# -le 1 ] || usage; up; echo "$URL" ;;
    url)  [ $# -le 1 ] || usage; up >/dev/null; echo "$URL" ;;
    down) [ $# -le 2 ] || usage; down "${2:-}" ;;
    *)    usage ;;
esac
