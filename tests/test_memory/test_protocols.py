"""Tests for MemoryStoreProtocol."""

from src.memory.adapters.in_memory import InMemoryAdapter
from src.memory.protocols import MemoryStoreProtocol


class TestMemoryStoreProtocol:
    """Tests for the runtime-checkable memory store protocol."""

    def test_in_memory_adapter_implements_protocol(self):
        adapter = InMemoryAdapter()
        assert isinstance(adapter, MemoryStoreProtocol)

    def test_protocol_is_runtime_checkable(self):
        """The protocol decorator should allow isinstance checks."""
        assert hasattr(MemoryStoreProtocol, "__protocol_attrs__") or hasattr(
            MemoryStoreProtocol, "_is_runtime_protocol"
        )

    def test_class_with_missing_methods_fails_protocol(self):

        class Incomplete:
            def add(self, scope, content, memory_type, metadata=None):
                pass

        obj = Incomplete()
        assert not isinstance(obj, MemoryStoreProtocol)

    def test_class_with_all_methods_passes_protocol(self):

        class Complete:
            def add(self, scope, content, memory_type, metadata=None):
                pass

            def search(self, scope, query, limit=5, threshold=0.0, memory_type=None):
                pass

            def get_all(self, scope, memory_type=None):
                pass

            def delete(self, scope, memory_id):
                pass

            def delete_all(self, scope):
                pass

        obj = Complete()
        assert isinstance(obj, MemoryStoreProtocol)

    def test_protocol_method_signatures(self):
        """Protocol should define the expected methods."""
        expected_methods = {"add", "search", "get_all", "delete", "delete_all"}
        # Protocol attrs can be checked by inspecting the class
        for method_name in expected_methods:
            assert hasattr(MemoryStoreProtocol, method_name)
