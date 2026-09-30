"""A word to the owner, from temper's bot, about temper itself.

Not a notice about a run -- those belong to the notify layer, which decides
where each one goes (``temper_ai/integrations/notify``). This is the channel
temper uses to talk about *itself*: the CI watcher's red/green DM
(``scripts/ci_watch.py``), temper-deploy's restart notes, and the message a
start-up sends about the runs it picked back up.

One bot, one place, wherever the message is written. The owner is the first
person the agent tools may DM in the Slack config (``agents``); ``EPD_OWNER_
SLACK_DM`` or ``TEMPER_OWNER_SLACK_DM`` name him instead when they are set.

``scripts/ci_watch.py`` writes into the same DM with its own few lines of
urllib: it runs from cron, outside temper's venv, and importing the package
would be a heavier promise than a watcher should make. ``EPD_OWNER_SLACK_DM``
is read here for exactly that reason -- it is the name the watcher already
uses, so both land with the same person however it is set.

Never raises. A message that cannot be sent is logged and life goes on -- the
work it describes has already happened.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# The watcher's name for it first, so the two cannot drift apart.
OWNER_ENVS = ("EPD_OWNER_SLACK_DM", "TEMPER_OWNER_SLACK_DM")


def owner_dm() -> str:
    """The owner's Slack user id, or "" when nobody is set."""
    from_env = next((v for v in (os.environ.get(e, "").strip() for e in OWNER_ENVS) if v), "")
    if from_env:
        return from_env
    try:
        from temper_ai.integrations.slack.config import load_config

        return next(iter(load_config().agents.users), "")
    except Exception:
        logger.debug("No Slack config to take the owner from", exc_info=True)
        return ""


def tell_owner(text: str) -> bool:
    """DM the owner from temper's bot. False (with a note in the log) when it could not go."""
    if not text.strip():
        return False
    try:
        from temper_ai.integrations.slack.client import SlackClient, bot_token
    except Exception:  # pragma: no cover - defensive
        logger.warning("Slack is not available: %s", text.splitlines()[0])
        return False

    user = owner_dm()
    if not bot_token() or not user:
        logger.warning("No Slack bot token or no owner set, so this went nowhere: %s",
                       text.splitlines()[0])
        return False
    try:
        client = _client() or SlackClient()
        client.post(client.open_dm(user), text)
        return True
    except Exception as exc:  # noqa: BLE001 - a failed DM must never stop the caller
        logger.warning("Could not DM the owner (%s): %s", exc, text.splitlines()[0])
        return False


def _client():
    """The signed-in client of the Slack service, when this process runs one."""
    try:
        from temper_ai.integrations.slack.service import running

        service = running()
        return service.client if service is not None else None
    except Exception:  # pragma: no cover - defensive
        return None
