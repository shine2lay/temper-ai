"""Tests for portfolio SQLModel table models."""

import uuid
from datetime import datetime

from temper_ai.portfolio.models import (
    KGConceptRecord,
    KGEdgeRecord,
    PortfolioRecord,
    PortfolioSnapshotRecord,
    ProductRunRecord,
    SharedComponentRecord,
    TechCompatibilityRecord,
)


class TestPortfolioRecord:
    def test_create_with_required_fields(self):
        record = PortfolioRecord(id="p1", name="my-portfolio")
        assert record.id == "p1"
        assert record.name == "my-portfolio"

    def test_description_defaults_to_empty_string(self):
        record = PortfolioRecord(id="p1", name="portfolio")
        assert record.description == ""

    def test_config_defaults_to_empty_dict(self):
        record = PortfolioRecord(id="p1", name="portfolio")
        assert record.config == {}

    def test_enabled_defaults_to_true(self):
        record = PortfolioRecord(id="p1", name="portfolio")
        assert record.enabled is True

    def test_created_at_is_datetime(self):
        record = PortfolioRecord(id="p1", name="portfolio")
        assert isinstance(record.created_at, datetime)

    def test_updated_at_defaults_to_none(self):
        record = PortfolioRecord(id="p1", name="portfolio")
        assert record.updated_at is None

    def test_explicit_values_set_correctly(self):
        record = PortfolioRecord(
            id="p2",
            name="test",
            description="desc",
            config={"key": "val"},
            enabled=False,
        )
        assert record.description == "desc"
        assert record.config == {"key": "val"}
        assert record.enabled is False

    def test_tablename(self):
        assert PortfolioRecord.__tablename__ == "portfolios"


class TestProductRunRecord:
    def _make(self, **kwargs) -> ProductRunRecord:
        defaults = {
            "id": str(uuid.uuid4()),
            "portfolio_id": "portfolio-1",
            "product_type": "web_app",
            "workflow_id": "wf-1",
        }
        defaults.update(kwargs)
        return ProductRunRecord(**defaults)

    def test_create_with_required_fields(self):
        record = self._make()
        assert record.portfolio_id == "portfolio-1"
        assert record.product_type == "web_app"
        assert record.workflow_id == "wf-1"

    def test_status_defaults_to_running(self):
        assert self._make().status == "running"

    def test_cost_defaults_to_zero(self):
        assert self._make().cost_usd == 0.0

    def test_duration_defaults_to_zero(self):
        assert self._make().duration_s == 0.0

    def test_success_defaults_to_false(self):
        assert self._make().success is False

    def test_metadata_json_defaults_to_empty_dict(self):
        assert self._make().metadata_json == {}

    def test_started_at_is_datetime(self):
        assert isinstance(self._make().started_at, datetime)

    def test_completed_at_defaults_to_none(self):
        assert self._make().completed_at is None

    def test_tablename(self):
        assert ProductRunRecord.__tablename__ == "product_runs"


class TestSharedComponentRecord:
    def _make(self, **kwargs) -> SharedComponentRecord:
        defaults = {
            "id": str(uuid.uuid4()),
            "source_stage": "web_app/build",
            "target_stage": "api/build",
        }
        defaults.update(kwargs)
        return SharedComponentRecord(**defaults)

    def test_create_with_required_fields(self):
        record = self._make()
        assert record.source_stage == "web_app/build"
        assert record.target_stage == "api/build"

    def test_similarity_defaults_to_zero(self):
        assert self._make().similarity == 0.0

    def test_shared_keys_defaults_to_empty_list(self):
        assert self._make().shared_keys == []

    def test_differing_keys_defaults_to_empty_list(self):
        assert self._make().differing_keys == []

    def test_status_defaults_to_detected(self):
        assert self._make().status == "detected"

    def test_created_at_is_datetime(self):
        assert isinstance(self._make().created_at, datetime)

    def test_tablename(self):
        assert SharedComponentRecord.__tablename__ == "shared_components"


class TestKGConceptRecord:
    def _make(self, **kwargs) -> KGConceptRecord:
        defaults = {
            "id": str(uuid.uuid4()),
            "name": "my-concept",
            "concept_type": "product",
        }
        defaults.update(kwargs)
        return KGConceptRecord(**defaults)

    def test_create_with_required_fields(self):
        record = self._make()
        assert record.name == "my-concept"
        assert record.concept_type == "product"

    def test_properties_defaults_to_empty_dict(self):
        assert self._make().properties == {}

    def test_created_at_is_datetime(self):
        assert isinstance(self._make().created_at, datetime)

    def test_tablename(self):
        assert KGConceptRecord.__tablename__ == "kg_concepts"


class TestKGEdgeRecord:
    def _make(self, **kwargs) -> KGEdgeRecord:
        defaults = {
            "id": str(uuid.uuid4()),
            "source_id": "concept-1",
            "target_id": "concept-2",
            "relation": "uses",
        }
        defaults.update(kwargs)
        return KGEdgeRecord(**defaults)

    def test_create_with_required_fields(self):
        record = self._make()
        assert record.source_id == "concept-1"
        assert record.target_id == "concept-2"
        assert record.relation == "uses"

    def test_weight_defaults_to_one(self):
        assert self._make().weight == 1.0

    def test_properties_defaults_to_empty_dict(self):
        assert self._make().properties == {}

    def test_created_at_is_datetime(self):
        assert isinstance(self._make().created_at, datetime)

    def test_tablename(self):
        assert KGEdgeRecord.__tablename__ == "kg_edges"


class TestTechCompatibilityRecord:
    def _make(self, **kwargs) -> TechCompatibilityRecord:
        defaults = {
            "id": str(uuid.uuid4()),
            "tech_a": "python",
            "tech_b": "fastapi",
        }
        defaults.update(kwargs)
        return TechCompatibilityRecord(**defaults)

    def test_create_with_required_fields(self):
        record = self._make()
        assert record.tech_a == "python"
        assert record.tech_b == "fastapi"

    def test_compatibility_score_defaults_to_zero(self):
        assert self._make().compatibility_score == 0.0

    def test_notes_defaults_to_empty_string(self):
        assert self._make().notes == ""

    def test_created_at_is_datetime(self):
        assert isinstance(self._make().created_at, datetime)

    def test_tablename(self):
        assert TechCompatibilityRecord.__tablename__ == "tech_compatibility"


class TestPortfolioSnapshotRecord:
    def _make(self, **kwargs) -> PortfolioSnapshotRecord:
        defaults = {
            "id": str(uuid.uuid4()),
            "portfolio_id": "port-1",
            "product_type": "web_app",
        }
        defaults.update(kwargs)
        return PortfolioSnapshotRecord(**defaults)

    def test_create_with_required_fields(self):
        record = self._make()
        assert record.portfolio_id == "port-1"
        assert record.product_type == "web_app"

    def test_success_rate_defaults_to_zero(self):
        assert self._make().success_rate == 0.0

    def test_cost_efficiency_defaults_to_zero(self):
        assert self._make().cost_efficiency == 0.0

    def test_trend_defaults_to_zero(self):
        assert self._make().trend == 0.0

    def test_utilization_defaults_to_zero(self):
        assert self._make().utilization == 0.0

    def test_composite_score_defaults_to_zero(self):
        assert self._make().composite_score == 0.0

    def test_created_at_is_datetime(self):
        assert isinstance(self._make().created_at, datetime)

    def test_tablename(self):
        assert PortfolioSnapshotRecord.__tablename__ == "portfolio_snapshots"
