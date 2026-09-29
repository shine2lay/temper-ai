"""Temper AI — experiment freely, improve visibly, ship safely."""

from temper_ai.integrations.github import secret as _github_secret

__version__ = "0.1.0"

# The GitHub app's private key and webhook secret leave the environment before
# anything here can start a child process: from now on only temper's own code
# holds them (see integrations.github.secret).
_github_secret.take()
