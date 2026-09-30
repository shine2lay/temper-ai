#!/usr/bin/env bash
# Put the weekly trim timer in place and start it.
#
#   bash scripts/systemd/install-trim.sh
#
# Runs as the owner, not as root: it uses the owner's uv and the owner's
# access to the database port. Nothing here needs a new key.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
units="$HOME/.config/systemd/user"
bin="$HOME/.local/bin"
mkdir -p "$units" "$bin" "$HOME/.local/state/temper-trim"

for unit in temper-trim.service temper-trim.timer; do
    install -m 0644 "$here/$unit" "$units/$unit"
    echo "installed $units/$unit"
done

# The command on the PATH points at the main checkout, so `temper-trim` keeps
# working after the worktree that added it is landed and removed.
ln -sfn "$HOME/temper-ai/scripts/temper-trim" "$bin/temper-trim"
echo "linked $bin/temper-trim -> ~/temper-ai/scripts/temper-trim"

systemctl --user daemon-reload
systemctl --user enable --now temper-trim.timer
systemctl --user --no-pager list-timers temper-trim.timer

echo
echo "temper-trim --dry-run   — what the next pass would do, changing nothing"
echo "~/.local/state/temper-trim/trim.log — one JSON line per pass"
