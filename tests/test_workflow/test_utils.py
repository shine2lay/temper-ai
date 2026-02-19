"""Tests for compiler utility functions."""
from temper_ai.workflow.utils import extract_agent_name


class MockAgent:
    """Mock agent class for testing."""
    def __init__(self, name=None, agent_name=None):
        if name is not None:
            self.name = name
        if agent_name is not None:
            self.agent_name = agent_name


class TestExtractAgentName:
    """Tests for extract_agent_name utility function."""

    def test_extract_from_string(self):
        """Test extracting name from string."""
        assert extract_agent_name("analyzer") == "analyzer"

    def test_extract_from_dict_with_name(self):
        """Test extracting from dict with 'name' key."""
        agent_ref = {"name": "analyzer"}
        assert extract_agent_name(agent_ref) == "analyzer"

    def test_extract_from_dict_with_agent_name(self):
        """Test extracting from dict with 'agent_name' key."""
        agent_ref = {"agent_name": "analyzer"}
        assert extract_agent_name(agent_ref) == "analyzer"

    def test_extract_from_dict_prefers_name_over_agent_name(self):
        """Test that 'name' is preferred over 'agent_name'."""
        agent_ref = {"name": "primary", "agent_name": "secondary"}
        assert extract_agent_name(agent_ref) == "primary"

    def test_extract_from_dict_falls_back_to_str(self):
        """Test fallback to str() when no name keys present."""
        agent_ref = {"id": 123, "type": "analyzer"}
        result = extract_agent_name(agent_ref)
        assert isinstance(result, str)
        assert "id" in result or "type" in result

    def test_extract_from_object_with_name(self):
        """Test extracting from object with 'name' attribute."""
        agent = MockAgent(name="analyzer")
        assert extract_agent_name(agent) == "analyzer"

    def test_extract_from_object_with_agent_name(self):
        """Test extracting from object with 'agent_name' attribute."""
        agent = MockAgent(agent_name="analyzer")
        assert extract_agent_name(agent) == "analyzer"

    def test_extract_from_object_prefers_name_over_agent_name(self):
        """Test that 'name' attribute is preferred."""
        agent = MockAgent(name="primary", agent_name="secondary")
        assert extract_agent_name(agent) == "primary"

    def test_extract_from_object_falls_back_to_str(self):
        """Test fallback to str() when no name attributes."""
        agent = MockAgent()  # No name or agent_name
        result = extract_agent_name(agent)
        assert isinstance(result, str)
        # Should be str representation of the mock object
        assert "MockAgent" in result

    def test_handles_none_values_in_dict(self):
        """Test handling None values in dict keys."""
        agent_ref = {"name": None, "agent_name": "analyzer"}
        assert extract_agent_name(agent_ref) == "analyzer"

    def test_handles_none_attributes_in_object(self):
        """Test handling None values in object attributes."""
        agent = MockAgent(name=None, agent_name="analyzer")
        assert extract_agent_name(agent) == "analyzer"

    def test_empty_string_is_valid_name(self):
        """Test that empty string is a valid name."""
        assert extract_agent_name("") == ""

    def test_unicode_name_handling(self):
        """Test handling of unicode characters in names."""
        agent_ref = {"name": "分析器"}
        assert extract_agent_name(agent_ref) == "分析器"
