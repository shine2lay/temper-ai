#!/usr/bin/env bash
# Install (or refresh) temper's user timers.
#
#   scripts/systemd/install.sh          install and start
#   scripts/systemd/install.sh --status show what is running
#
# User units, not system ones: they run as the owner, read the owner's
# ~/temper-ai/.env for the Slack token, and need no root.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNITS=(temper-ci-watch.service temper-ci-watch.timer)

if [ "${1:-}" = "--status" ]; then
    systemctl --user list-timers --all 'temper-*' --no-pager
    systemctl --user status temper-ci-watch.service --no-pager -n 20 || true
    exit 0
fi

mkdir -p "$DEST"
for unit in "${UNITS[@]}"; do
    install -m 0644 "$HERE/$unit" "$DEST/$unit"
    echo "installed $DEST/$unit"
done

systemctl --user daemon-reload
systemctl --user enable --now temper-ci-watch.timer
echo
systemctl --user list-timers --all 'temper-ci-watch*' --no-pager
echo
echo "Try it:  python3 $HOME/temper-ai/scripts/ci_watch.py --test"
