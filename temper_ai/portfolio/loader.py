"""Portfolio YAML config loader."""

import logging
from pathlib import Path

import yaml

from temper_ai.portfolio._schemas import PortfolioConfig
from temper_ai.portfolio.constants import DEFAULT_PORTFOLIO_CONFIG_DIR

logger = logging.getLogger(__name__)


class PortfolioLoader:
    """Load portfolio definitions from YAML configs."""

    def __init__(self, config_dir: str | None = None) -> None:
        self.config_dir = Path(config_dir or DEFAULT_PORTFOLIO_CONFIG_DIR)

    def load(self, name: str) -> PortfolioConfig:
        """Load a portfolio config by name.

        Looks for ``<config_dir>/<name>.yaml``.

        Raises:
            FileNotFoundError: If the config file does not exist.
            ValueError: If the config is invalid.
        """
        path = self.config_dir / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Portfolio config not found: {path}")
        return self._parse_file(path)

    def list_available(self) -> list[str]:
        """List available portfolio config names."""
        if not self.config_dir.exists():
            return []
        return sorted(p.stem for p in self.config_dir.glob("*.yaml"))

    def load_from_path(self, path: str) -> PortfolioConfig:
        """Load a portfolio config from an explicit file path.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the config is invalid.
        """
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Portfolio config not found: {path}")
        return self._parse_file(file_path)

    def _parse_file(self, path: Path) -> PortfolioConfig:
        """Parse a YAML file into a PortfolioConfig."""
        with open(path) as f:
            raw = yaml.safe_load(f)
        if not raw:
            raise ValueError(f"Empty portfolio config: {path}")
        try:
            return PortfolioConfig(**raw)
        except Exception as exc:
            raise ValueError(f"Invalid portfolio config {path}: {exc}") from exc
