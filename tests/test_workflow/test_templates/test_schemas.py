"""Tests for template manifest and quality gate schemas."""

import pytest
from pydantic import ValidationError

from temper_ai.workflow.templates._schemas import (
    TemplateDefaultInference,
    TemplateManifest,
    TemplateQualityGates,
)


class TestTemplateQualityGates:
    """Tests for TemplateQualityGates schema."""

    def test_defaults(self):
        qg = TemplateQualityGates()
        assert qg.enabled is True
        assert qg.min_confidence == 0.7
        assert qg.require_citations is True
        assert qg.on_failure == "retry_stage"
        assert qg.max_retries == 3
        assert qg.custom_checks == []

    def test_custom_values(self):
        qg = TemplateQualityGates(
            min_confidence=0.9,
            require_citations=False,
            on_failure="escalate",
            custom_checks=["check_a", "check_b"],
        )
        assert qg.min_confidence == 0.9
        assert qg.require_citations is False
        assert qg.on_failure == "escalate"
        assert qg.custom_checks == ["check_a", "check_b"]

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            TemplateQualityGates(min_confidence=1.5)
        with pytest.raises(ValidationError):
            TemplateQualityGates(min_confidence=-0.1)

    def test_invalid_on_failure(self):
        with pytest.raises(ValidationError):
            TemplateQualityGates(on_failure="invalid_value")

    def test_max_retries_non_negative(self):
        with pytest.raises(ValidationError):
            TemplateQualityGates(max_retries=-1)


class TestTemplateDefaultInference:
    """Tests for TemplateDefaultInference schema."""

    def test_defaults(self):
        inf = TemplateDefaultInference()
        assert inf.provider == "vllm"
        assert inf.model == "qwen3-next"
        assert inf.base_url == "http://localhost:8000"


class TestTemplateManifest:
    """Tests for TemplateManifest schema."""

    def test_minimal_manifest(self):
        m = TemplateManifest(
            product_type="api",
            name="Test API",
            description="A test API template",
        )
        assert m.product_type == "api"
        assert m.name == "Test API"
        assert m.version == "1.0"
        assert m.stages == []
        assert m.tags == []

    def test_full_manifest(self):
        m = TemplateManifest(
            product_type="web_app",
            name="Web App",
            description="Full web app",
            version="2.0",
            required_inputs=["project_description"],
            optional_inputs=["style_guide"],
            quality_gates=TemplateQualityGates(min_confidence=0.8),
            stages=["design", "code", "test"],
            tags=["web", "fullstack"],
        )
        assert m.version == "2.0"
        assert len(m.stages) == 3
        assert m.quality_gates.min_confidence == 0.8

    def test_invalid_product_type(self):
        with pytest.raises(ValidationError):
            TemplateManifest(
                product_type="invalid_type",
                name="Bad",
                description="Bad template",
            )

    def test_all_valid_product_types(self):
        valid_types = [
            "web_app",
            "mobile_app",
            "api",
            "data_product",
            "data_pipeline",
            "cli_tool",
        ]
        for pt in valid_types:
            m = TemplateManifest(
                product_type=pt,
                name=f"Test {pt}",
                description=f"Template for {pt}",
            )
            assert m.product_type == pt
