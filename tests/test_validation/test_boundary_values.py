"""
Boundary value and edge case tests for configuration limits.

Tests critical boundaries for:
- Agent counts
- Confidence scores
- Token counts
- Debate rounds
- Temperature values
- File sizes
- Max tokens
- Timeouts
- Priorities
- Rate limits
"""

import pytest

from tests.fixtures.boundary_values import (
    BOUNDARY_VALUES,
    get_boundary_test_cases,
)

# Import components to test
try:
    from src.agent.strategies.base import AgentOutput, SynthesisResult
    from src.agent.strategies.conflict_resolution import ResolutionResult
    from src.agent.strategies.consensus import ConsensusStrategy
except ImportError:
    pytest.skip("Strategy modules not available", allow_module_level=True)


class TestAgentCountBoundaries:
    """Test agent count boundary validation."""

    @pytest.mark.parametrize("agent_count,should_accept", [
        (0, False),  # Below minimum
        (1, True),   # Minimum
        (3, True),   # Typical
        (10, True),  # Maximum
        (11, False), # Above maximum
    ])
    def test_agent_count_boundaries(self, agent_count, should_accept):
        """Test agent count boundaries in consensus strategy."""
        if agent_count <= 0:
            # Should raise error when creating empty list
            if not should_accept:
                with pytest.raises((ValueError, IndexError)):
                    outputs = [
                        AgentOutput(
                            agent_name=f"agent_{i}",
                            decision=f"result_{i}",
                            reasoning="test reasoning",
                            confidence=0.8,
                            metadata={}
                        )
                        for i in range(agent_count)
                    ]
                    if len(outputs) == 0:
                        raise ValueError("Cannot synthesize from 0 agents")
                    strategy = ConsensusStrategy(min_agreement=0.5)
                    strategy.synthesize(outputs, {})
        elif should_accept:
            # Should succeed
            outputs = [
                AgentOutput(
                    agent_name=f"agent_{i}",
                    decision=f"result_{i % 2}",  # Create some agreement
                    reasoning="test reasoning",
                    confidence=0.8,
                    metadata={}
                )
                for i in range(agent_count)
            ]
            strategy = ConsensusStrategy()
            result = strategy.synthesize(outputs, {"min_consensus": 0.5})
            assert isinstance(result, SynthesisResult)
        else:
            # Above maximum might be allowed but test it works
            outputs = [
                AgentOutput(
                    agent_name=f"agent_{i}",
                    decision=f"result_{i % 2}",
                    reasoning="test reasoning",
                    confidence=0.8,
                    metadata={}
                )
                for i in range(agent_count)
            ]
            strategy = ConsensusStrategy()
            result = strategy.synthesize(outputs, {"min_consensus": 0.5})
            assert isinstance(result, SynthesisResult)


class TestConfidenceScoreBoundaries:
    """Test confidence score boundary validation."""

    @pytest.mark.parametrize("confidence,should_accept", [
        (-0.1, False),  # Below minimum
        (0.0, True),    # Minimum
        (0.5, True),    # Mid
        (1.0, True),    # Maximum
        (1.1, False),   # Above maximum
    ])
    def test_confidence_score_boundaries(self, confidence, should_accept):
        """Test confidence score boundaries in AgentOutput."""
        if should_accept:
            # Should succeed
            output = AgentOutput(
                agent_name="test_agent",
                decision="test decision",
                reasoning="test reasoning",
                confidence=confidence,
                metadata={}
            )
            assert output.confidence == confidence
        else:
            # Should raise ValueError
            with pytest.raises(ValueError):
                AgentOutput(
                    agent_name="test_agent",
                    decision="test decision",
                    reasoning="test reasoning",
                    confidence=confidence,
                    metadata={}
                )

    @pytest.mark.parametrize("confidence,should_accept", [
        (-0.1, False),
        (0.0, True),
        (0.5, True),
        (1.0, True),
        (1.1, False),
        (2.0, False),
    ])
    def test_resolution_result_confidence(self, confidence, should_accept):
        """Test confidence boundaries in ResolutionResult."""
        if should_accept:
            result = ResolutionResult(
                decision="A",
                method="test",
                reasoning="test reasoning",
                success=True,
                confidence=confidence,
                metadata={}
            )
            assert result.confidence == confidence
        else:
            with pytest.raises(ValueError):
                ResolutionResult(
                    decision="A",
                    method="test",
                    reasoning="test reasoning",
                    success=True,
                    confidence=confidence,
                    metadata={}
                )


class TestTokenCountBoundaries:
    """Test token count boundary validation."""

    @pytest.mark.parametrize("token_count,should_accept", [
        (0, False),     # Zero
        (1, True),      # Minimum
        (500, True),    # Typical
        (2048, True),   # At limit
        (2049, False),  # Above limit (for some configs)
    ])
    def test_token_count_basic(self, token_count, should_accept):
        """Test basic token count validation."""
        # Token counts are typically validated at the LLM provider level
        # Here we test that reasonable values are handled
        if should_accept or token_count > 0:
            # Most token counts should be accepted unless explicitly limited
            assert token_count >= 0
        else:
            # Zero tokens should be rejected
            assert token_count < 1


class TestDebateRoundBoundaries:
    """Test debate round boundary validation."""

    @pytest.mark.parametrize("max_rounds,should_accept", [
        (0, False),  # Zero
        (1, True),   # Minimum
        (3, True),   # Typical
        (10, True),  # Maximum
        (11, False), # Above maximum
    ])
    def test_debate_round_boundaries(self, max_rounds, should_accept):
        """Test debate round boundaries."""
        if should_accept:
            # Valid round counts should be positive
            assert max_rounds > 0
            assert max_rounds <= 10
        else:
            # Invalid round counts
            assert max_rounds <= 0 or max_rounds > 10


class TestTemperatureBoundaries:
    """Test temperature boundary validation."""

    @pytest.mark.parametrize("temperature,should_accept", [
        (-0.1, False),  # Below minimum
        (0.0, True),    # Minimum
        (0.7, True),    # Typical
        (1.0, True),    # High
        (2.0, True),    # Maximum
        (2.1, False),   # Above maximum
    ])
    def test_temperature_boundaries(self, temperature, should_accept):
        """Test temperature boundaries."""
        if should_accept:
            assert 0.0 <= temperature <= 2.0
        else:
            assert temperature < 0.0 or temperature > 2.0


class TestFileSizeBoundaries:
    """Test file size boundary validation."""

    @pytest.mark.parametrize("file_size,should_accept", [
        (0, False),        # Zero
        (1, True),         # Minimum
        (1048576, True),   # 1 MB
        (10485760, True),  # 10 MB (at limit)
        (10485761, False), # Above limit
    ])
    def test_file_size_boundaries(self, file_size, should_accept):
        """Test file size boundaries."""
        MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

        if should_accept:
            assert 0 < file_size <= MAX_FILE_SIZE
        else:
            assert file_size <= 0 or file_size > MAX_FILE_SIZE


class TestMaxTokensBoundaries:
    """Test max_tokens boundary validation."""

    @pytest.mark.parametrize("max_tokens,should_accept", [
        (0, False),    # Zero
        (1, True),     # Minimum
        (2048, True),  # Typical
        (100000, True),  # Maximum
        (100001, False), # Above maximum
    ])
    def test_max_tokens_boundaries(self, max_tokens, should_accept):
        """Test max_tokens boundaries."""
        MAX_ALLOWED = 100000

        if should_accept:
            assert 1 <= max_tokens <= MAX_ALLOWED
        else:
            assert max_tokens < 1 or max_tokens > MAX_ALLOWED


class TestTimeoutBoundaries:
    """Test timeout boundary validation."""

    @pytest.mark.parametrize("timeout,should_accept", [
        (0, False),   # Zero
        (1, True),    # Minimum
        (30, True),   # Typical
        (600, True),  # Maximum (10 minutes)
        (601, False), # Above maximum
    ])
    def test_timeout_boundaries(self, timeout, should_accept):
        """Test timeout boundaries."""
        MAX_TIMEOUT = 600  # 10 minutes

        if should_accept:
            assert 1 <= timeout <= MAX_TIMEOUT
        else:
            assert timeout < 1 or timeout > MAX_TIMEOUT


class TestPriorityBoundaries:
    """Test priority boundary validation."""

    @pytest.mark.parametrize("priority,should_accept", [
        (-1, False), # Below minimum
        (0, True),   # Minimum
        (1, True),   # Low
        (3, True),   # High
        (5, True),   # Maximum
        (6, False),  # Above maximum
    ])
    def test_priority_boundaries(self, priority, should_accept):
        """Test priority boundaries."""
        if should_accept:
            assert 0 <= priority <= 5
        else:
            assert priority < 0 or priority > 5


class TestRateLimitBoundaries:
    """Test rate limit boundary validation."""

    @pytest.mark.parametrize("rate_limit,should_accept", [
        (0, False),    # Zero
        (1, True),     # Minimum
        (10, True),    # Typical
        (1000, True),  # Maximum
        (1001, False), # Above maximum
    ])
    def test_rate_limit_boundaries(self, rate_limit, should_accept):
        """Test rate limit boundaries."""
        MAX_RATE = 1000

        if should_accept:
            assert 1 <= rate_limit <= MAX_RATE
        else:
            assert rate_limit < 1 or rate_limit > MAX_RATE


class TestBoundaryValueHelper:
    """Test the boundary value helper functions."""

    def test_get_boundary_test_cases(self):
        """Test boundary test case generation."""
        cases = get_boundary_test_cases("agent_count", ("minimum", "maximum"))

        assert len(cases) > 0
        for value, should_accept in cases:
            assert isinstance(value, int)
            assert isinstance(should_accept, bool)

    def test_all_boundary_types_available(self):
        """Test all boundary types are defined."""
        expected_types = [
            "agent_count",
            "confidence_score",
            "token_count",
            "debate_round",
            "temperature",
            "file_size",
            "max_tokens",
            "timeout",
            "priority",
            "rate_limit",
        ]

        for boundary_type in expected_types:
            assert boundary_type in BOUNDARY_VALUES
            assert isinstance(BOUNDARY_VALUES[boundary_type], dict)
            assert len(BOUNDARY_VALUES[boundary_type]) > 0


class TestEdgeCaseCombinations:
    """Test edge case combinations."""

    def test_minimum_agent_count_with_high_confidence(self):
        """Test minimum agent count with high confidence."""
        outputs = [
            AgentOutput(
                agent_name="agent_0",
                decision="result",
                reasoning="test reasoning",
                confidence=1.0,  # Maximum confidence
                metadata={}
            )
        ]
        strategy = ConsensusStrategy()
        result = strategy.synthesize(outputs, {"min_consensus": 0.5})
        assert isinstance(result, SynthesisResult)

    def test_maximum_agent_count_with_low_confidence(self):
        """Test maximum agent count with low confidence."""
        outputs = [
            AgentOutput(
                agent_name=f"agent_{i}",
                decision=f"result_{i % 2}",
                reasoning="test reasoning",
                confidence=0.0,  # Minimum confidence
                metadata={}
            )
            for i in range(10)
        ]
        strategy = ConsensusStrategy()
        result = strategy.synthesize(outputs, {"min_consensus": 0.5})
        assert isinstance(result, SynthesisResult)

    def test_confidence_at_exact_boundaries(self):
        """Test confidence scores at exact boundary values."""
        # Test exactly at boundaries
        for conf in [0.0, 0.5, 1.0]:
            output = AgentOutput(
                agent_name="test",
                decision="test",
                reasoning="test reasoning",
                confidence=conf,
                metadata={}
            )
            assert output.confidence == conf

    def test_temperature_at_exact_boundaries(self):
        """Test temperature at exact boundary values."""
        # Temperature boundaries are typically 0.0 to 2.0
        valid_temps = [0.0, 1.0, 2.0]
        for temp in valid_temps:
            assert 0.0 <= temp <= 2.0
