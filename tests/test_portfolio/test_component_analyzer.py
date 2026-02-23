"""Tests for ComponentAnalyzer."""

import os
import tempfile

import pytest
import yaml

from temper_ai.portfolio._schemas import PortfolioConfig, ProductDefinition
from temper_ai.portfolio.component_analyzer import ComponentAnalyzer
from temper_ai.portfolio.store import PortfolioStore

MEMORY_DB = "sqlite:///:memory:"


@pytest.fixture
def store():
    return PortfolioStore(database_url=MEMORY_DB)


@pytest.fixture
def analyzer(store):
    return ComponentAnalyzer(store=store)


class TestJaccardSimilarity:
    def test_jaccard_identical(self):
        result = ComponentAnalyzer.jaccard_similarity({"a", "b", "c"}, {"a", "b", "c"})
        assert result == pytest.approx(1.0)

    def test_jaccard_disjoint(self):
        result = ComponentAnalyzer.jaccard_similarity({"a", "b"}, {"c", "d"})
        assert result == pytest.approx(0.0)

    def test_jaccard_partial_overlap(self):
        result = ComponentAnalyzer.jaccard_similarity({"a", "b", "c"}, {"b", "c", "d"})
        assert result == pytest.approx(0.5)

    def test_jaccard_empty_both(self):
        result = ComponentAnalyzer.jaccard_similarity(set(), set())
        assert result == pytest.approx(0.0)

    def test_jaccard_one_empty(self):
        result = ComponentAnalyzer.jaccard_similarity({"a"}, set())
        assert result == pytest.approx(0.0)

    def test_jaccard_single_element(self):
        result = ComponentAnalyzer.jaccard_similarity({"a"}, {"a"})
        assert result == pytest.approx(1.0)


class TestAnalyzePortfolio:
    def test_analyze_portfolio_finds_matches(self, analyzer):
        """Create two workflow configs with similar stages and verify matches."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Both workflows have stages with the same keys
            wf1_path = os.path.join(tmpdir, "wf1.yaml")
            wf2_path = os.path.join(tmpdir, "wf2.yaml")

            stage_def = {
                "name": "build",
                "timeout": 300,
                "retries": 3,
                "error_handling": "retry",
                "agents": ["builder"],
            }

            with open(wf1_path, "w") as f:
                yaml.dump({"stages": [stage_def]}, f)
            with open(wf2_path, "w") as f:
                yaml.dump({"stages": [stage_def]}, f)

            portfolio = PortfolioConfig(
                name="test",
                products=[
                    ProductDefinition(name="web_app", workflow_configs=[wf1_path]),
                    ProductDefinition(name="api", workflow_configs=[wf2_path]),
                ],
            )
            matches = analyzer.analyze_portfolio(portfolio)
            assert len(matches) >= 1
            assert matches[0].similarity >= 0.6

    def test_analyze_portfolio_no_matches(self, analyzer):
        """Different stage configs should produce no matches."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wf1_path = os.path.join(tmpdir, "wf1.yaml")
            wf2_path = os.path.join(tmpdir, "wf2.yaml")

            with open(wf1_path, "w") as f:
                yaml.dump({"stages": [{"name": "build", "x": 1}]}, f)
            with open(wf2_path, "w") as f:
                yaml.dump({"stages": [{"name": "deploy", "y": 1, "z": 1, "w": 1}]}, f)

            portfolio = PortfolioConfig(
                name="test",
                products=[
                    ProductDefinition(name="web_app", workflow_configs=[wf1_path]),
                    ProductDefinition(name="api", workflow_configs=[wf2_path]),
                ],
            )
            matches = analyzer.analyze_portfolio(portfolio)
            assert len(matches) == 0

    def test_analyze_empty_portfolio(self, analyzer):
        portfolio = PortfolioConfig(name="empty", products=[])
        matches = analyzer.analyze_portfolio(portfolio)
        assert matches == []

    def test_analyze_missing_configs(self, analyzer):
        portfolio = PortfolioConfig(
            name="missing",
            products=[
                ProductDefinition(
                    name="web_app",
                    workflow_configs=["/nonexistent/path.yaml"],
                ),
            ],
        )
        matches = analyzer.analyze_portfolio(portfolio)
        assert matches == []


class TestFindSimilarStages:
    def test_find_similar_stages(self, analyzer, store):
        """Insert shared component records and find similar stages."""
        from temper_ai.portfolio.models import SharedComponentRecord

        store.save_shared_component(
            SharedComponentRecord(
                id="sc1",
                source_stage="web_app/build",
                target_stage="api/build",
                similarity=0.9,
                shared_keys=["name", "timeout"],
                differing_keys=["retries"],
            )
        )
        results = analyzer.find_similar_stages(
            {"name": "x", "timeout": 100},
            "web_app",
            min_similarity=0.5,
        )
        assert len(results) >= 1
        assert results[0].similarity >= 0.5

    def test_min_similarity_filter(self, analyzer, store):
        from temper_ai.portfolio.models import SharedComponentRecord

        store.save_shared_component(
            SharedComponentRecord(
                id="sc1",
                source_stage="web_app/low",
                target_stage="api/low",
                similarity=0.3,
                shared_keys=["name"],
            )
        )
        results = analyzer.find_similar_stages(
            {"name": "x"},
            "web_app",
            min_similarity=0.5,
        )
        assert len(results) == 0


class TestComponentMatchDetails:
    def test_component_match_shared_keys(self, analyzer):
        with tempfile.TemporaryDirectory() as tmpdir:
            wf1 = os.path.join(tmpdir, "wf1.yaml")
            wf2 = os.path.join(tmpdir, "wf2.yaml")
            shared_stage = {
                "name": "test",
                "timeout": 60,
                "retries": 3,
                "mode": "parallel",
            }
            with open(wf1, "w") as f:
                yaml.dump({"stages": [shared_stage]}, f)
            with open(wf2, "w") as f:
                yaml.dump({"stages": [shared_stage]}, f)

            portfolio = PortfolioConfig(
                name="test",
                products=[
                    ProductDefinition(name="a", workflow_configs=[wf1]),
                    ProductDefinition(name="b", workflow_configs=[wf2]),
                ],
            )
            matches = analyzer.analyze_portfolio(portfolio)
            assert len(matches) >= 1
            assert len(matches[0].shared_keys) > 0

    def test_component_match_differing_keys(self, analyzer):
        with tempfile.TemporaryDirectory() as tmpdir:
            wf1 = os.path.join(tmpdir, "wf1.yaml")
            wf2 = os.path.join(tmpdir, "wf2.yaml")
            # Stages share most keys but differ on one
            with open(wf1, "w") as f:
                yaml.dump(
                    {"stages": [{"name": "s", "a": 1, "b": 2, "c": 3}]},
                    f,
                )
            with open(wf2, "w") as f:
                yaml.dump(
                    {"stages": [{"name": "s", "a": 1, "b": 2, "d": 4}]},
                    f,
                )

            portfolio = PortfolioConfig(
                name="test",
                products=[
                    ProductDefinition(name="x", workflow_configs=[wf1]),
                    ProductDefinition(name="y", workflow_configs=[wf2]),
                ],
            )
            matches = analyzer.analyze_portfolio(portfolio)
            assert len(matches) >= 1
            assert len(matches[0].differing_keys) > 0

    def test_saves_to_store(self, analyzer, store):
        with tempfile.TemporaryDirectory() as tmpdir:
            wf1 = os.path.join(tmpdir, "wf1.yaml")
            wf2 = os.path.join(tmpdir, "wf2.yaml")
            stage = {"name": "deploy", "timeout": 120, "retries": 2, "mode": "seq"}
            with open(wf1, "w") as f:
                yaml.dump({"stages": [stage]}, f)
            with open(wf2, "w") as f:
                yaml.dump({"stages": [stage]}, f)

            portfolio = PortfolioConfig(
                name="test",
                products=[
                    ProductDefinition(name="p1", workflow_configs=[wf1]),
                    ProductDefinition(name="p2", workflow_configs=[wf2]),
                ],
            )
            matches = analyzer.analyze_portfolio(portfolio)
            stored = store.list_shared_components()
            assert len(stored) == len(matches)
