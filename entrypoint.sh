#!/bin/sh
# Symlink the latest Claude Code binary from the mounted versions dir.
# Versions are semver dirs (e.g., 2.1.92); pick the newest by sort.
if [ -d /opt/claude/versions ]; then
    latest=$(ls /opt/claude/versions | sort -V | tail -1)
    if [ -n "$latest" ]; then
        ln -sf "/opt/claude/versions/$latest" /app/.local/bin/claude
    fi
fi

exec "$@"
