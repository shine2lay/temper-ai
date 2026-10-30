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
# On Linux with Docker's own engine (rootful, not Docker Desktop) it runs on the
# host's network and listens on 127.0.0.1 only. The tests then reach it over
# loopback instead of through Docker's userland proxy, which has to wake up for
# every round trip and, on a busy machine, makes each one wait for a core
# (docs/testing.md). Elsewhere it runs on Docker's bridge with its port
# published on 127.0.0.1, as before. TEMPER_TEST_PG_NETWORK=host or bridge
# chooses for a container this script starts; a running one is kept as it is.
# The URL is the same either way.
#
# Never temper's live database: this container has a name of its own, a port
# of its own, and keeps everything in RAM (tmpfs), so removing it leaves
# nothing behind. The tests refuse a URL that could be the live one anyway
# (tests/pgtier.py).
set -euo pipefail

# Same central contract as the box/build fixtures. Inactive keeps the old
# singleton; enabled never adopts or touches that container, even for down.
PARENT_CONTRACT="$(dirname "$(realpath "${BASH_SOURCE[0]}")")/../tests/test_spawner/test_container_parent.py"
PARENT=""
parent_args=()
if PARENT=$(python3 "$PARENT_CONTRACT" parent); then
    parent_args=("--cgroup-parent=$PARENT")
    NAME="${TEMPER_TEST_PG_NAME:-temper-test-postgres-cpu}"
    PORT="${TEMPER_TEST_PG_PORT:-5456}"
    if [[ ! "$NAME" =~ ^temper-test-postgres-cpu(-[a-zA-Z0-9_-]+)?$ ]] \
        || [[ ! "$PORT" =~ ^[1-9][0-9]{3,4}$ ]] \
        || [ "$PORT" -gt 65535 ] || [[ "$PORT" = 5432 || "$PORT" = 5433 || "$PORT" = 5455 ]]; then
        echo "test-postgres.sh: enabled tests require a separate temper-test-postgres-cpu name and non-live port (default 5456)." >&2
        exit 1
    fi
else
    status=$?
    [ "$status" = 3 ] || exit "$status"
    NAME="${TEMPER_TEST_PG_NAME:-temper-test-postgres}"
    PORT="${TEMPER_TEST_PG_PORT:-5455}"  # live temper is on 5433
fi
IMAGE="${TEMPER_TEST_PG_IMAGE:-pgvector/pgvector:pg16}"
NETWORK="${TEMPER_TEST_PG_NETWORK:-}"    # host, bridge, or empty: host where it works
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

# Over the container's unix socket, on the port its server was started with
# (the container's PGPORT; 5432 when it has none).
psql_in() {
    docker exec "$NAME" psql -U temper_ai -d "$DB" -XAtq -c "$1"
}

# Whether something takes a TCP connection on 127.0.0.1:$PORT, here. Bash's
# /dev/tcp, so there is nothing to install; on loopback it answers or refuses
# at once.
answers() {
    local -a limit=()
    if command -v timeout >/dev/null; then
        limit=(timeout 5)
    fi
    ${limit[@]+"${limit[@]}"} bash -c 'exec 3<>"/dev/tcp/127.0.0.1/$1"' _ "$PORT" 2>/dev/null
}

# The host's network is this machine's only with Docker's own engine on Linux,
# run as root. Docker Desktop runs containers in a VM, and rootless Docker in a
# network namespace of its own: there the container's 127.0.0.1 is not ours.
default_network() {
    local info
    if [ "$(uname -s)" != Linux ] \
        || ! info=$(docker info --format '{{.OperatingSystem}}|{{json .SecurityOptions}}' 2>/dev/null); then
        echo bridge
        return
    fi
    case "${info%%|*}" in
        "Docker Desktop"*) echo bridge; return ;;
    esac
    case "${info#*|}" in
        *name=rootless*) echo bridge; return ;;
    esac
    echo host
}

start() {
    local mode=$1
    local -a net=() listen=()
    if [ "$mode" = host ]; then
        # The server takes the port itself, and only on 127.0.0.1: the host's
        # network also reaches the LAN and tailscale, and it must never listen there.
        net=(--network host -e PGPORT="$PORT")
        listen=(-c listen_addresses=127.0.0.1)
    else
        net=(-p "127.0.0.1:${PORT}:5432")
    fi
    # size=4g: up to five builds run their suites here at the same time
    # (2026-10-05), each in schemas of its own, and 512 MB was a third full
    # with nothing running. A tmpfs takes RAM only for what it holds, so the
    # cap costs nothing until it is used. max_wal_size: Postgres keeps up to
    # 1 GB of write-ahead log by default; here it stays near 128 MB.
    # max_connections: a run takes up to ~30, and several runs share the
    # container. --auth-host: a login over TCP needs the password. The image
    # would trust any login from 127.0.0.1, which on the host's network is
    # every process on this machine. The labels say which of these settings a
    # container has.
    docker run -d --name "$NAME" \
        --label temper.test-pg.version=4 --label temper.test-pg.network="$mode" \
        "${parent_args[@]}" "${net[@]}" \
        -e POSTGRES_DB="$DB" -e POSTGRES_USER=temper_ai -e POSTGRES_PASSWORD=test \
        -e POSTGRES_INITDB_ARGS=--auth-host=scram-sha-256 \
        -e PGDATA=/var/lib/postgresql/data/pgdata \
        --tmpfs /var/lib/postgresql/data:rw,size=4g \
        "$IMAGE" \
        ${listen[@]+"${listen[@]}"} \
        -c fsync=off -c full_page_writes=off -c synchronous_commit=off \
        -c max_wal_size=128MB -c min_wal_size=32MB -c max_connections=300 >/dev/null
}

# Ready means our own server answers. First on the container's unix socket with
# listen_addresses set: while the image sets the database up it runs a server
# with none, which answers and then stops. Then on 127.0.0.1:$PORT from here.
# A container that stops on the way fails at once, with its logs.
wait_ready() {
    local state listening
    for _ in $(seq 1 120); do
        state=$(docker inspect -f '{{.State.Status}}' "$NAME" 2>/dev/null || echo "not there")
        if [ "$state" != running ]; then
            echo "test postgres $NAME stopped before it answered ($state); docker logs $NAME:" >&2
            docker logs --tail 30 "$NAME" >&2 || true
            return 1
        fi
        listening=$(psql_in "SHOW listen_addresses" 2>/dev/null || true)
        if [ -n "$listening" ]; then
            reachable
            return
        fi
        sleep 0.5
    done
    echo "test postgres $NAME did not answer within a minute; docker logs $NAME:" >&2
    docker logs --tail 30 "$NAME" >&2 || true
    return 1
}

reachable() {
    for _ in $(seq 1 20); do
        if answers; then
            return 0
        fi
        sleep 0.5
    done
    echo "test-postgres.sh: $NAME is up, but nothing answers on 127.0.0.1:$PORT from here." >&2
    if [ "$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$NAME" 2>/dev/null || true)" = host ]; then
        echo "  It is on Docker's host network, which is not this machine's here (a VM?)." >&2
        echo "  Start it on the bridge instead: $0 down; TEMPER_TEST_PG_NETWORK=bridge $0 up" >&2
    fi
    return 1
}

up() {
    take_lock
    if [ -n "$PARENT" ] && docker container inspect "$NAME" >/dev/null 2>&1; then
        # Validate BEFORE the old stopped-container replacement path. An
        # off-parent stopped container is not ours to delete, either.
        python3 "$PARENT_CONTRACT" verify "$NAME" --stopped
    fi
    if ! running; then
        # Nobody can be using a container that is not running: one that exists
        # (it stopped, or its start failed) is replaced. A running one never is.
        docker rm -f "$NAME" >/dev/null 2>&1 || true
        if answers; then
            echo "test-postgres.sh: something already answers on 127.0.0.1:$PORT, so $NAME is not started there." >&2
            echo "  Stop what holds port $PORT, or give the container another one (TEMPER_TEST_PG_PORT)." >&2
            exit 1
        fi
        start "${NETWORK:-$(default_network)}"
    fi
    if [ -n "$PARENT" ]; then
        python3 "$PARENT_CONTRACT" verify "$NAME"
    fi
    wait_ready
    if [ -n "$PARENT" ]; then
        # A listener on the requested port alone is not proof it is this DB.
        local mode actual
        mode=$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$NAME")
        if [ "$mode" = host ]; then
            actual=$(psql_in "SHOW port")
            [ "$actual" = "$PORT" ] || { echo "test-postgres.sh: reused PG port mismatch" >&2; return 1; }
        else
            actual=$(docker port "$NAME" 5432/tcp)
            [ "$actual" = "127.0.0.1:$PORT" ] || { echo "test-postgres.sh: reused PG binding mismatch" >&2; return 1; }
        fi
    fi
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
    if [ -n "$PARENT" ]; then
        python3 "$PARENT_CONTRACT" verify "$NAME" --stopped
        # Active-parent adoption never makes --force safe for a live shared DB.
        [ "$force" = 0 ] || { echo "test-postgres.sh: enabled test PG refuses forced cleanup" >&2; return 1; }
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

case "$NETWORK" in
    ""|host|bridge) ;;
    *)  echo "test-postgres.sh: TEMPER_TEST_PG_NETWORK must be host or bridge (or unset), not '$NETWORK'." >&2
        exit 2 ;;
esac

case "${1:-url}" in
    up)   [ $# -le 1 ] || usage; up; echo "$URL" ;;
    url)  [ $# -le 1 ] || usage; up >/dev/null; echo "$URL" ;;
    down) [ $# -le 2 ] || usage; down "${2:-}" ;;
    *)    usage ;;
esac
