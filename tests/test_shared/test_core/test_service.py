"""Tests for temper_ai/shared/core/service.py."""

import pytest

from temper_ai.shared.core.service import Service


class _ConcreteService(Service):
    """Concrete implementation for testing."""

    @property
    def name(self) -> str:
        return "test-service"


class TestService:
    """Tests for the Service abstract base class."""

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            Service()  # type: ignore[abstract]

    def test_concrete_service_name(self):
        svc = _ConcreteService()
        assert svc.name == "test-service"

    def test_initialize_is_noop_by_default(self):
        svc = _ConcreteService()
        svc.initialize()  # Should not raise

    def test_shutdown_is_noop_by_default(self):
        svc = _ConcreteService()
        svc.shutdown()  # Should not raise

    def test_subclass_must_implement_name(self):
        with pytest.raises(TypeError):

            class _NoName(Service):
                pass

            _NoName()  # type: ignore[abstract]
