"""Optional config-file and .env loading.

Reads ``~/.temper/config.yaml`` (if present) and injects its values as
environment variables **before** ``TemperSettings`` is constructed.  Because
env vars set later by the user take precedence over these injected values,
the priority hierarchy is preserved:

    CLI flags  >  real env vars  >  config.yaml  >  defaults
"""

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".temper"
CONFIG_FILE = CONFIG_DIR / "config.yaml"


def load_config_file() -> dict[str, Any]:
    """Load ``~/.temper/config.yaml`` and return its contents.

    Returns an empty dict when the file does not exist or cannot be parsed.
    """
    if not CONFIG_FILE.is_file():
        return {}

    try:
        import yaml

        with open(CONFIG_FILE) as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict):
            logger.warning("~/.temper/config.yaml is not a mapping — ignoring")
            return {}
        logger.debug("Loaded config from %s", CONFIG_FILE)
        return dict(data)
    except ImportError:
        logger.debug("PyYAML not available — skipping config file")
        return {}
    except Exception:  # noqa: BLE001 — config file is optional
        logger.warning("Failed to parse %s — ignoring", CONFIG_FILE, exc_info=True)
        return {}


def inject_config_as_env(config: dict[str, Any]) -> list[str]:
    """Inject config-file values as ``TEMPER_*`` env vars (lowest priority).

    Only sets a variable when it is **not** already present in the
    environment, so real env vars and CLI flags always win.

    Returns:
        List of env var names that were injected.
    """
    injected: list[str] = []
    for key, value in config.items():
        env_name = f"TEMPER_{key.upper()}"
        if os.environ.get(env_name) is None:
            os.environ[env_name] = str(value)
            injected.append(env_name)
            logger.debug("Injected %s from config file", env_name)
    return injected
