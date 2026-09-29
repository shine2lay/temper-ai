#!/usr/bin/env bash
# Put temper-ci's two user services in place and start them.
#
#   bash scripts/systemd/install.sh
#
# Both run as the owner, not as root: the check needs the owner's docker,
# the owner's `gh` login (no new key anywhere) and the owner's temper-deploy.
# Neither unit is ever started by GitHub — GitHub cannot reach this machine,
# which is the whole reason the check is here and not on a runner.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
units="$HOME/.config/systemd/user"
bin="$HOME/.local/bin"
mkdir -p "$units" "$bin"

for unit in temper-ci.service temper-ci-reports.service; do
    install -m 0644 "$here/$unit" "$units/$unit"
    echo "installed $units/$unit"
done

# The command on the PATH points at the main checkout, so `temper-ci` keeps
# working after the worktree that added it is landed and removed.
ln -sfn "$HOME/temper-ai/scripts/temper-ci" "$bin/temper-ci"
echo "linked $bin/temper-ci -> ~/temper-ai/scripts/temper-ci"

systemctl --user daemon-reload
systemctl --user enable --now temper-ci-reports.service
systemctl --user enable --now temper-ci.service
systemctl --user --no-pager status temper-ci.service temper-ci-reports.service | head -20
echo
echo "temper-ci status   — what it is checking, the last deploy, the last good commit"
