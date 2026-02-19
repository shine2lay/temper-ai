"""Tests for PortfolioLoader."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from temper_ai.portfolio.loader import PortfolioLoader


class TestPortfolioLoader:
    def test_load_example_portfolio(self):
        loader = PortfolioLoader(config_dir="configs/portfolios")
        cfg = loader.load("example_portfolio")
        assert cfg.name == "example_portfolio"
        assert len(cfg.products) == 3
        assert cfg.products[0].name == "web_app"

    def test_load_nonexistent(self):
        loader = PortfolioLoader(config_dir="configs/portfolios")
        with pytest.raises(FileNotFoundError):
            loader.load("nonexistent_portfolio_xyz")

    def test_list_available(self):
        loader = PortfolioLoader(config_dir="configs/portfolios")
        available = loader.list_available()
        assert isinstance(available, list)
        assert "example_portfolio" in available

    def test_load_invalid_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_path = Path(tmpdir) / "bad.yaml"
            bad_path.write_text("name: 123\nproducts: not_a_list")
            loader = PortfolioLoader(config_dir=tmpdir)
            with pytest.raises(ValueError):
                loader.load("bad")

    def test_load_from_path(self):
        loader = PortfolioLoader()
        cfg = loader.load_from_path("configs/portfolios/example_portfolio.yaml")
        assert cfg.name == "example_portfolio"
        assert cfg.strategy.value == "weighted"
