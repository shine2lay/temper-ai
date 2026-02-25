"""Realistic test data fixtures for more meaningful testing.

This module provides production-like test data to replace minimal mocks
and empty configurations. Using realistic data helps catch more edge cases
and makes tests more representative of actual usage.
"""

import copy
from typing import Any

from temper_ai.storage.schemas.agent_config import (
    AgentConfig,
    AgentConfigInner,
    ErrorHandlingConfig,
    InferenceConfig,
    PromptConfig,
)

# Realistic agent configurations
REALISTIC_RESEARCH_AGENT = AgentConfig(
    agent=AgentConfigInner(
        name="research_agent",
        description="Expert research agent for information gathering",
        version="1.0",
        type="standard",
        prompt=PromptConfig(
            inline="""You are an expert research agent responsible for gathering
and analyzing information from multiple sources. Your role is to provide
comprehensive, fact-based research summaries with citations. {{input}}"""
        ),
        inference=InferenceConfig(
            provider="ollama",
            model="llama2",
            base_url="http://localhost:11434",
            temperature=0.7,
            max_tokens=2000,
        ),
        tools=["web_search", "document_reader", "citation_formatter"],
        error_handling=ErrorHandlingConfig(
            retry_strategy="ExponentialBackoff", fallback="GracefulDegradation"
        ),
    )
)

REALISTIC_ANALYST_AGENT = AgentConfig(
    agent=AgentConfigInner(
        name="analyst_agent",
        description="Critical analyst for data-driven insights",
        version="1.0",
        type="standard",
        prompt=PromptConfig(
            inline="""You are a critical analyst who evaluates research findings,
identifies patterns, and provides data-driven insights. {{input}}"""
        ),
        inference=InferenceConfig(
            provider="ollama",
            model="llama2",
            base_url="http://localhost:11434",
            temperature=0.5,
            max_tokens=1500,
        ),
        tools=["statistical_analysis", "data_visualization", "calculator"],
        error_handling=ErrorHandlingConfig(
            retry_strategy="ExponentialBackoff", fallback="GracefulDegradation"
        ),
    )
)

REALISTIC_SYNTHESIS_AGENT = AgentConfig(
    agent=AgentConfigInner(
        name="synthesis_agent",
        description="Synthesis agent for actionable recommendations",
        version="1.0",
        type="standard",
        prompt=PromptConfig(
            inline="""You are a synthesis agent that combines insights from
research and analysis to create comprehensive, actionable recommendations. {{input}}"""
        ),
        inference=InferenceConfig(
            provider="ollama",
            model="llama2",
            base_url="http://localhost:11434",
            temperature=0.6,
            max_tokens=3000,
        ),
        tools=["summarizer", "report_generator"],
        error_handling=ErrorHandlingConfig(
            retry_strategy="ExponentialBackoff", fallback="GracefulDegradation"
        ),
    )
)

REALISTIC_CODE_AGENT = AgentConfig(
    agent=AgentConfigInner(
        name="code_agent",
        description="Expert software developer",
        version="1.0",
        type="standard",
        prompt=PromptConfig(
            inline="""You are an expert software developer who writes clean,
well-tested, production-ready code. {{input}}"""
        ),
        inference=InferenceConfig(
            provider="ollama",
            model="llama2",
            base_url="http://localhost:11434",
            temperature=0.3,
            max_tokens=4000,
        ),
        tools=["test_runner", "linter", "debugger"],
        error_handling=ErrorHandlingConfig(
            retry_strategy="ExponentialBackoff", fallback="GracefulDegradation"
        ),
    )
)

REALISTIC_REVIEW_AGENT = AgentConfig(
    agent=AgentConfigInner(
        name="review_agent",
        description="Meticulous code reviewer",
        version="1.0",
        type="standard",
        prompt=PromptConfig(
            inline="""You are a meticulous code reviewer who ensures code quality,
security, and maintainability. {{input}}"""
        ),
        inference=InferenceConfig(
            provider="ollama",
            model="llama2",
            base_url="http://localhost:11434",
            temperature=0.4,
            max_tokens=2000,
        ),
        tools=["static_analyzer", "security_scanner", "complexity_checker"],
        error_handling=ErrorHandlingConfig(
            retry_strategy="ExponentialBackoff", fallback="GracefulDegradation"
        ),
    )
)


# Realistic agent lists for different scenarios
REALISTIC_RESEARCH_WORKFLOW_AGENTS = [
    REALISTIC_RESEARCH_AGENT,
    REALISTIC_ANALYST_AGENT,
    REALISTIC_SYNTHESIS_AGENT,
]

REALISTIC_CODE_WORKFLOW_AGENTS = [REALISTIC_CODE_AGENT, REALISTIC_REVIEW_AGENT]

REALISTIC_MULTI_AGENT_TEAM = [
    REALISTIC_RESEARCH_AGENT,
    REALISTIC_ANALYST_AGENT,
    REALISTIC_SYNTHESIS_AGENT,
    REALISTIC_CODE_AGENT,
    REALISTIC_REVIEW_AGENT,
]


# Realistic workflow configurations (as dictionaries for compatibility)
# These are used by tests that don't need full Pydantic validation

REALISTIC_RESEARCH_WORKFLOW_DICT = {
    "workflow": {
        "name": "research_workflow",
        "description": "Multi-stage research and analysis workflow",
        "stages": ["research", "analysis", "synthesis"],
        "metadata": {
            "workflow_type": "research_pipeline",
            "version": "1.0.0",
            "author": "research_team",
            "created_date": "2026-01-15",
            "tags": ["research", "analysis", "synthesis"],
            "priority": "high",
            "estimated_duration": 750,
            "max_retries": 3,
            "retry_strategy": "exponential_backoff",
            "error_handling": "fail_fast",
        },
    }
}

REALISTIC_CODE_REVIEW_WORKFLOW_DICT = {
    "workflow": {
        "name": "code_review_workflow",
        "description": "Automated code development and review workflow",
        "stages": ["development", "review"],
        "metadata": {
            "workflow_type": "code_pipeline",
            "version": "2.1.0",
            "author": "dev_team",
            "created_date": "2026-01-20",
            "tags": ["development", "code_review", "quality"],
            "priority": "critical",
            "estimated_duration": 900,
            "max_retries": 2,
            "retry_strategy": "immediate",
            "error_handling": "rollback",
        },
    }
}


# Realistic agent outputs for consensus testing
REALISTIC_AGENT_OUTPUTS_UNANIMOUS = [
    {
        "agent": "research_agent",
        "decision": "Approach A",
        "reasoning": "Extensive research shows that Approach A has the strongest empirical support with 15 peer-reviewed studies demonstrating effectiveness.",
        "confidence": 0.92,
        "metadata": {
            "sources": 15,
            "citation_quality": "high",
            "consensus_in_literature": 0.89,
        },
    },
    {
        "agent": "analyst_agent",
        "decision": "Approach A",
        "reasoning": "Statistical analysis of historical data reveals that Approach A outperforms alternatives by 34% on key metrics with p < 0.01.",
        "confidence": 0.88,
        "metadata": {
            "sample_size": 10000,
            "statistical_significance": 0.001,
            "effect_size": 0.34,
        },
    },
    {
        "agent": "synthesis_agent",
        "decision": "Approach A",
        "reasoning": "Synthesizing research and analysis, Approach A emerges as the clear winner with both theoretical and empirical support.",
        "confidence": 0.90,
        "metadata": {
            "supporting_evidence": "strong",
            "risk_assessment": "low",
            "implementation_difficulty": "moderate",
        },
    },
]

REALISTIC_AGENT_OUTPUTS_MAJORITY = [
    {
        "agent": "research_agent",
        "decision": "Approach A",
        "reasoning": "Research indicates Approach A is well-established with proven track record in 12 studies.",
        "confidence": 0.85,
        "metadata": {"sources": 12, "publication_years": "2020-2025"},
    },
    {
        "agent": "analyst_agent",
        "decision": "Approach A",
        "reasoning": "Data analysis shows Approach A has 28% better performance metrics than alternatives.",
        "confidence": 0.82,
        "metadata": {"performance_gain": 0.28, "confidence_interval": "(0.21, 0.35)"},
    },
    {
        "agent": "synthesis_agent",
        "decision": "Approach B",
        "reasoning": "While Approach A has strong support, Approach B offers better long-term scalability and maintainability.",
        "confidence": 0.75,
        "metadata": {
            "consideration": "long_term_scalability",
            "trade_off": "performance_vs_maintainability",
        },
    },
]

REALISTIC_AGENT_OUTPUTS_SPLIT = [
    {
        "agent": "research_agent",
        "decision": "Approach A",
        "reasoning": "Literature supports Approach A for immediate results.",
        "confidence": 0.78,
        "metadata": {"focus": "short_term"},
    },
    {
        "agent": "analyst_agent",
        "decision": "Approach B",
        "reasoning": "Analytical models suggest Approach B is more robust.",
        "confidence": 0.80,
        "metadata": {"focus": "robustness"},
    },
    {
        "agent": "synthesis_agent",
        "decision": "Approach C",
        "reasoning": "Hybrid Approach C combines benefits of both.",
        "confidence": 0.76,
        "metadata": {"focus": "hybrid_solution"},
    },
]


# Realistic complex nested metadata
REALISTIC_COMPLEX_METADATA = {
    "project_info": {
        "name": "autonomous_research_system",
        "version": "3.2.1",
        "environment": "production",
        "region": "us-west-2",
    },
    "execution_context": {
        "user_id": "user_12345",
        "session_id": "sess_abc789xyz",
        "request_id": "req_987654321",
        "timestamp": "2026-01-31T10:30:00Z",
        "timezone": "UTC",
    },
    "performance_config": {
        "timeout_ms": 30000,
        "max_retries": 3,
        "retry_delay_ms": 1000,
        "circuit_breaker": {"enabled": True, "threshold": 5, "timeout_seconds": 60},
    },
    "quality_gates": {
        "min_confidence": 0.7,
        "require_citations": True,
        "fact_checking": "enabled",
        "bias_detection": {"enabled": True, "sensitivity": "high"},
    },
    "observability": {
        "tracing": {"enabled": True, "sample_rate": 0.1, "exporter": "jaeger"},
        "metrics": {
            "enabled": True,
            "namespace": "autonomous_workflows",
            "dimensions": ["stage", "agent", "status"],
        },
        "logging": {"level": "INFO", "format": "json", "redact_pii": True},
    },
    "security": {
        "authentication": "oauth2",
        "authorization": "rbac",
        "encryption_at_rest": True,
        "encryption_in_transit": True,
        "audit_logging": True,
    },
    "cost_tracking": {
        "enabled": True,
        "budget_alert_threshold": 1000.00,
        "currency": "USD",
        "cost_allocation_tags": {
            "team": "research",
            "project": "autonomous_ai",
            "environment": "prod",
        },
    },
}


# Helper function to create realistic workflow configurations
def create_realistic_workflow_config(
    name: str = "test_workflow", num_stages: int = 3, include_metadata: bool = True
) -> dict[str, Any]:
    """Create a realistic workflow configuration for testing.

    Args:
        name: Workflow name
        num_stages: Number of stages to include (1-5)
        include_metadata: Whether to include complex metadata

    Returns:
        Dictionary containing realistic workflow configuration
    """
    stage_types = ["research", "analysis", "synthesis", "development", "review"]
    selected_stages = stage_types[: min(num_stages, len(stage_types))]

    config: dict[str, Any] = {"workflow": {"name": name, "stages": selected_stages}}

    if include_metadata:
        config["workflow"]["metadata"] = REALISTIC_COMPLEX_METADATA

    return config


# ============================================================================
# NODE CREATION FUNCTIONS (for test_stage_compiler.py)
# ============================================================================


def create_realistic_init_node():
    """Create a realistic initialization node for testing.

    Returns a function that initializes workflow state with realistic fields.
    This replaces Mock() objects in tests to provide actual initialization logic.

    Returns:
        Callable that initializes state dict with realistic workflow metadata

    Example:
        >>> init_node = create_realistic_init_node()
        >>> state = {}
        >>> result = init_node(state)
        >>> assert "metadata" in result
        >>> assert result["workflow_id"]
    """

    def init_node(state):
        """Initialize workflow state with realistic metadata."""
        state["workflow_id"] = state.get("workflow_id", "workflow_test_123")
        state["stage_outputs"] = {}
        state["current_stage"] = ""
        state["num_stages"] = 0
        state["version"] = "1.0"
        state["metadata"] = {
            "initialized_at": "2026-01-31T10:00:00Z",
            "user_id": "test_user_456",
            "environment": "test",
            "session_id": "session_789",
        }
        return state

    return init_node


def create_realistic_stage_node(
    stage_name: str, output_data: dict[str, Any] | None = None
):
    """Create a realistic stage node for testing.

    Returns a function that simulates stage execution with realistic outputs.
    This replaces Mock() objects in tests to provide actual stage execution logic.

    Args:
        stage_name: Name of the stage (e.g., "research", "analysis", "synthesis")
        output_data: Optional custom output data. If None, uses realistic defaults
                     based on stage type.

    Returns:
        Callable that executes stage and produces realistic output

    Example:
        >>> stage_node = create_realistic_stage_node("research")
        >>> state = {"stage_outputs": {}}
        >>> result = stage_node(state)
        >>> assert "research" in result["stage_outputs"]
        >>> assert result["stage_outputs"]["research"]["confidence"] > 0.7
    """

    def stage_node(state):
        """Execute stage and produce realistic output."""
        state["stage_outputs"] = state.get("stage_outputs", {})
        state["current_stage"] = stage_name

        # Realistic output based on stage type
        if output_data:
            state["stage_outputs"][stage_name] = output_data
        else:
            # Default realistic outputs by stage type
            realistic_outputs = {
                "research": {
                    "summary": "Comprehensive research findings with 12 sources analyzed",
                    "citations": [
                        "Source A (2024)",
                        "Source B (2025)",
                        "Source C (2023)",
                    ],
                    "confidence": 0.87,
                    "key_findings": [
                        "Finding 1: Positive trend observed",
                        "Finding 2: Statistical significance confirmed",
                        "Finding 3: Replication studies support claims",
                    ],
                },
                "analysis": {
                    "insights": "Statistical analysis reveals 28% improvement over baseline",
                    "metrics": {
                        "performance": 0.92,
                        "accuracy": 0.89,
                        "precision": 0.91,
                    },
                    "confidence": 0.85,
                    "visualizations": ["chart_1.png", "graph_2.png", "heatmap_3.png"],
                },
                "synthesis": {
                    "recommendation": "Recommend Approach A based on converging evidence",
                    "confidence": 0.90,
                    "supporting_evidence": ["research output", "analysis output"],
                    "risk_assessment": "low",
                    "alternative_options": [
                        "Approach B (fallback)",
                        "Approach C (experimental)",
                    ],
                },
                "development": {
                    "implementation": "Developed prototype with core functionality",
                    "test_coverage": 0.85,
                    "confidence": 0.88,
                    "technical_debt": "minimal",
                    "dependencies": ["library_a==1.2.0", "library_b==2.3.1"],
                },
                "review": {
                    "quality_score": 0.92,
                    "issues_found": 3,
                    "critical_issues": 0,
                    "confidence": 0.91,
                    "recommendations": [
                        "Improve error handling",
                        "Add more unit tests",
                    ],
                },
            }
            state["stage_outputs"][stage_name] = realistic_outputs.get(
                stage_name, {"output": f"Completed {stage_name}", "confidence": 0.80}
            )

        return state

    return stage_node


# ============================================================================
# EXECUTOR CLASSES (for test_stage_compiler.py)
# ============================================================================


class RealisticSequentialExecutor:
    """Realistic sequential executor for testing.

    Simulates sequential execution behavior without actual LLM calls.
    Tracks execution history for test verification.

    Attributes:
        executions: List of (mode, agent_count, context) tuples tracking all executions

    Example:
        >>> executor = RealisticSequentialExecutor()
        >>> agents = [research_agent, analyst_agent]
        >>> results = executor.execute(agents, {"task": "analyze data"})
        >>> assert len(results) == 2
        >>> assert executor.executions[0][0] == "sequential"
    """

    def __init__(self):
        self.executions = []

    def execute(self, agents, context):
        """Execute agents sequentially with realistic output.

        Args:
            agents: List of agent configurations
            context: Execution context dict

        Returns:
            List of execution results with realistic metadata
        """
        self.executions.append(("sequential", len(agents), context))

        results = []
        for agent in agents:
            agent_name = agent.agent.name if hasattr(agent, "agent") else str(agent)
            results.append(
                {
                    "agent": agent_name,
                    "output": f"Sequential output from {agent_name}",
                    "success": True,
                    "duration_ms": 150.0,
                    "tokens_used": 450,
                    "execution_order": len(results) + 1,
                }
            )
        return results


class RealisticParallelExecutor:
    """Realistic parallel executor for testing.

    Simulates parallel execution behavior without actual LLM calls.
    Execution times are lower than sequential to reflect parallelism.

    Attributes:
        executions: List of (mode, agent_count, context) tuples tracking all executions

    Example:
        >>> executor = RealisticParallelExecutor()
        >>> agents = [research_agent, analyst_agent, synthesis_agent]
        >>> results = executor.execute(agents, {"task": "collaborate"})
        >>> assert len(results) == 3
        >>> assert all(r["thread_id"] for r in results)  # Each agent gets own thread
    """

    def __init__(self):
        self.executions = []

    def execute(self, agents, context):
        """Execute agents in parallel with realistic output.

        Args:
            agents: List of agent configurations
            context: Execution context dict

        Returns:
            List of execution results with realistic metadata
        """
        self.executions.append(("parallel", len(agents), context))

        # Simulate parallel execution - all agents execute simultaneously
        results = []
        for i, agent in enumerate(agents):
            agent_name = agent.agent.name if hasattr(agent, "agent") else str(agent)
            results.append(
                {
                    "agent": agent_name,
                    "output": f"Parallel output from {agent_name}",
                    "success": True,
                    "duration_ms": 120.0,  # Faster than sequential
                    "tokens_used": 420,
                    "thread_id": f"thread_{i}_{agent_name}",
                }
            )
        return results


class RealisticAdaptiveExecutor:
    """Realistic adaptive executor for testing.

    Adaptively chooses execution strategy based on number of agents.
    Uses parallel for >2 agents, sequential otherwise.

    Attributes:
        executions: List of (mode, agent_count, context) tuples tracking all executions
        mode: Current execution mode ("auto", "parallel", "sequential")

    Example:
        >>> executor = RealisticAdaptiveExecutor()
        >>> few_agents = [agent1, agent2]
        >>> many_agents = [agent1, agent2, agent3, agent4]
        >>>
        >>> results_sequential = executor.execute(few_agents, {})
        >>> assert results_sequential[0]["execution_mode"] == "sequential"
        >>>
        >>> results_parallel = executor.execute(many_agents, {})
        >>> assert results_parallel[0]["execution_mode"] == "parallel"
    """

    def __init__(self):
        self.executions = []
        self.mode = "auto"

    def execute(self, agents, context):
        """Adaptively choose execution strategy.

        Args:
            agents: List of agent configurations
            context: Execution context dict

        Returns:
            List of execution results with realistic metadata
        """
        self.executions.append(("adaptive", len(agents), context))

        # Adaptive logic: parallel for >2 agents, sequential otherwise
        execution_mode = "parallel" if len(agents) > 2 else "sequential"
        duration_ms = 120.0 if execution_mode == "parallel" else 150.0

        results = []
        for agent in agents:
            agent_name = agent.agent.name if hasattr(agent, "agent") else str(agent)
            results.append(
                {
                    "agent": agent_name,
                    "output": f"Adaptive ({execution_mode}) output from {agent_name}",
                    "success": True,
                    "duration_ms": duration_ms,
                    "tokens_used": 435,
                    "execution_mode": execution_mode,
                }
            )
        return results


# ============================================================================
# PERFORMANCE TRACKING CONTEXTS (for test_performance.py)
# ============================================================================

REALISTIC_PERFORMANCE_CONTEXTS = {
    "llm_call": {
        "model": "gpt-4-turbo",
        "provider": "openai",
        "endpoint": "/v1/chat/completions",
        "tokens_prompt": 1250,
        "tokens_completion": 680,
        "temperature": 0.7,
        "max_tokens": 2000,
        "user_id": "user_12345",
        "workflow_id": "wf_abc123",
        "stage_name": "research",
        "retry_count": 0,
    },
    "tool_execution": {
        "tool_name": "web_search",
        "tool_version": "2.1.0",
        "query": "autonomous AI frameworks 2026",
        "result_count": 15,
        "cache_hit": False,
        "workflow_id": "wf_abc123",
        "agent_name": "research_agent",
    },
    "stage_execution": {
        "stage_name": "analysis",
        "agent_count": 3,
        "strategy": "parallel",
        "workflow_id": "wf_abc123",
        "previous_stage": "research",
        "timeout_ms": 10000,
        "checkpoint_enabled": True,
    },
    "workflow_execution": {
        "workflow_name": "research_pipeline",
        "workflow_version": "3.2.1",
        "stage_count": 5,
        "total_agents": 12,
        "environment": "production",
        "user_id": "user_12345",
        "priority": "high",
    },
}

# Edge case performance contexts for timeout/error scenarios
REALISTIC_SLOW_OPERATION_CONTEXTS = {
    "timeout_scenario": {
        "operation": "llm_call",
        "timeout_ms": 5000,
        "actual_duration_ms": 6500,
        "timeout_exceeded": True,
        "model": "gpt-4",
        "retry_attempted": True,
        "final_status": "timeout_error",
    },
    "rate_limited": {
        "operation": "llm_call",
        "provider": "openai",
        "rate_limit_type": "requests_per_minute",
        "limit": 60,
        "current_usage": 61,
        "retry_after_seconds": 15,
        "final_status": "rate_limit_error",
    },
    "large_payload": {
        "operation": "tool_execution",
        "tool_name": "web_scraper",
        "payload_size_bytes": 10485760,  # 10MB
        "chunk_count": 42,
        "compression_enabled": True,
        "final_status": "success",
    },
}


# ============================================================================
# EDGE CASE FIXTURES (for comprehensive testing)
# ============================================================================

REALISTIC_EDGE_CASES = {
    "single_agent": [
        {
            "agent": "solo_agent",
            "decision": "Only Option",
            "reasoning": "As the only agent, I recommend this option based on comprehensive analysis of all available data, considering 8 different factors and 15 historical precedents.",
            "confidence": 0.85,
            "metadata": {
                "role": "generalist",
                "sources_consulted": 8,
                "factors_considered": 8,
            },
        }
    ],
    "low_confidence_agents": [
        {
            "agent": "uncertain_agent_1",
            "decision": "Option A",
            "reasoning": "Limited data suggests this might work, but sample size is small (n=15) and confidence intervals are wide.",
            "confidence": 0.45,
            "metadata": {"sample_size": 15, "uncertainty": "high"},
        },
        {
            "agent": "uncertain_agent_2",
            "decision": "Option A",
            "reasoning": "Not very confident but leaning towards this based on weak signal in preliminary results.",
            "confidence": 0.38,
            "metadata": {"signal_strength": "weak", "p_value": 0.12},
        },
        {
            "agent": "uncertain_agent_3",
            "decision": "Option B",
            "reasoning": "Insufficient evidence for clear decision - data quality issues make conclusions tentative.",
            "confidence": 0.42,
            "metadata": {"data_quality": "poor", "missing_values": 0.35},
        },
    ],
    "high_confidence_disagreement": [
        {
            "agent": "expert_1",
            "decision": "Option A",
            "reasoning": "Strongly believe A is optimal based on 20 years experience and deep domain expertise. Historical precedents overwhelmingly support this approach.",
            "confidence": 0.95,
            "metadata": {
                "expertise": "domain_expert",
                "years_experience": 20,
                "cases_reviewed": 150,
            },
        },
        {
            "agent": "expert_2",
            "decision": "Option B",
            "reasoning": "Completely disagree - B is clearly superior based on latest research (12 peer-reviewed papers published in 2025-2026). Expert 1's experience is outdated.",
            "confidence": 0.98,
            "metadata": {
                "expertise": "researcher",
                "publications": 12,
                "recency": "2025-2026",
            },
        },
    ],
    "large_agent_team": [
        {
            "agent": f"agent_{i}",
            "decision": f"Option {chr(65 + i % 3)}",  # A, B, C rotation
            "reasoning": f"Detailed reasoning from agent {i} based on specialized perspective and analysis of data subset {i}. Confidence based on {100 + i * 10} data points.",
            "confidence": 0.7 + (i % 3) * 0.1,
            "metadata": {
                "agent_id": i,
                "specialization": f"area_{i % 5}",
                "data_points": 100 + i * 10,
            },
        }
        for i in range(15)  # 15 agents for testing scale
    ],
    "empty_reasoning": [
        {
            "agent": "lazy_agent",
            "decision": "Option A",
            "reasoning": "",  # Empty reasoning
            "confidence": 0.6,
            "metadata": {"quality_issue": "no_reasoning_provided"},
        },
        {
            "agent": "normal_agent",
            "decision": "Option A",
            "reasoning": "Proper reasoning here based on thorough analysis and evidence review.",
            "confidence": 0.8,
            "metadata": {"quality": "good"},
        },
    ],
    "special_characters_in_decisions": [
        {
            "agent": "agent1",
            "decision": "Option: A (v2.0)",
            "reasoning": "Decision with special chars: colons, parentheses, and version numbers.",
            "confidence": 0.8,
            "metadata": {"version": "2.0"},
        },
        {
            "agent": "agent2",
            "decision": "Option: A (v2.0)",
            "reasoning": "Same decision format - testing deduplication and parsing.",
            "confidence": 0.75,
            "metadata": {"version": "2.0"},
        },
        {
            "agent": "agent3",
            "decision": "Option: B (v1.5)",
            "reasoning": "Different version - testing version handling in consensus.",
            "confidence": 0.7,
            "metadata": {"version": "1.5"},
        },
    ],
}


# ============================================================================
# HELPER FUNCTIONS (for test performance and convenience)
# ============================================================================


def get_realistic_agent_outputs_unanimous():
    """Get a fresh copy of unanimous agent outputs.

    Returns a deep copy to prevent test pollution while keeping
    performance fast (copy is faster than recreation).

    Returns:
        List of dicts with realistic unanimous agent outputs

    Example:
        >>> outputs = get_realistic_agent_outputs_unanimous()
        >>> assert len(outputs) == 3
        >>> assert all(o["decision"] == "Approach A" for o in outputs)
        >>> assert all(o["confidence"] > 0.85 for o in outputs)
    """
    return copy.deepcopy(REALISTIC_AGENT_OUTPUTS_UNANIMOUS)


def get_realistic_agent_outputs_majority():
    """Get a fresh copy of majority (2-1) agent outputs.

    Returns:
        List of dicts with realistic majority agent outputs
    """
    return copy.deepcopy(REALISTIC_AGENT_OUTPUTS_MAJORITY)


def get_realistic_agent_outputs_split():
    """Get a fresh copy of split (1-1-1) agent outputs.

    Returns:
        List of dicts with realistic split agent outputs
    """
    return copy.deepcopy(REALISTIC_AGENT_OUTPUTS_SPLIT)


def get_realistic_workflow_config_by_scenario(scenario: str = "research"):
    """Get a realistic workflow config by scenario.

    Args:
        scenario: One of 'research', 'code_review', 'custom'

    Returns:
        Pre-built config for speed, with deep copy for isolation

    Example:
        >>> config = get_realistic_workflow_config_by_scenario("research")
        >>> assert "workflow" in config
        >>> assert "metadata" in config
    """
    # Return basic config with metadata
    config = create_realistic_workflow_config(
        name=f"{scenario}_workflow", num_stages=3, include_metadata=True
    )
    return copy.deepcopy(config)


def get_realistic_edge_case(case_name: str):
    """Get a specific realistic edge case scenario.

    Args:
        case_name: One of the keys in REALISTIC_EDGE_CASES

    Returns:
        Deep copy of the edge case data

    Raises:
        KeyError: If case_name not found

    Example:
        >>> single_agent = get_realistic_edge_case("single_agent")
        >>> assert len(single_agent) == 1
        >>> assert single_agent[0]["confidence"] > 0.8
    """
    if case_name not in REALISTIC_EDGE_CASES:
        raise KeyError(
            f"Unknown edge case '{case_name}'. Available: {list(REALISTIC_EDGE_CASES.keys())}"
        )
    return copy.deepcopy(REALISTIC_EDGE_CASES[case_name])


# ==============================================================================
# MOCK REDUCTION FIXTURES - Phase 1 (Priority 1)
# ==============================================================================


class RealisticConfigLoader:
    """In-memory ConfigLoader for testing without filesystem dependencies.

    Replaces Mock(spec=ConfigLoader) with realistic behavior.
    This allows tests to use real config loading logic without file I/O.

    Example:
        >>> loader = RealisticConfigLoader()
        >>> agent_config = loader.load_agent("research_agent")
        >>> assert agent_config["agent"]["name"] == "research_agent"
    """

    def __init__(
        self,
        agents: dict[str, dict] | None = None,
        stages: dict[str, dict] | None = None,
    ):
        """Initialize with custom agent and stage configurations.

        Args:
            agents: Dict mapping agent names to agent config dicts
            stages: Dict mapping stage names to stage config dicts
        """
        self.agents = agents or {}
        self.stages = stages or {}

    def load_agent(self, agent_ref: str) -> dict[str, Any]:
        """Load agent config from in-memory store.

        Args:
            agent_ref: Agent reference name

        Returns:
            Agent configuration dict with all required fields
        """
        if agent_ref in self.agents:
            return copy.deepcopy(self.agents[agent_ref])

        # Return realistic default agent config
        return {
            "agent": {
                "name": agent_ref,
                "type": "standard",
                "description": f"Test agent {agent_ref}",
                "version": "1.0",
                "prompt": {"inline": f"You are {agent_ref}"},
                "inference": {
                    "provider": "ollama",
                    "model": "llama2",
                    "base_url": "http://localhost:11434",
                    "temperature": 0.7,
                    "max_tokens": 2000,
                },
                "tools": [],
                "error_handling": {
                    "retry_strategy": "ExponentialBackoff",
                    "fallback": "GracefulDegradation",
                },
            }
        }

    def load_stage(self, stage_ref: str) -> dict[str, Any]:
        """Load stage config from in-memory store.

        Args:
            stage_ref: Stage reference name

        Returns:
            Stage configuration dict with all required fields
        """
        if stage_ref in self.stages:
            return copy.deepcopy(self.stages[stage_ref])

        # Return realistic default stage config
        return {
            "stage": {"name": stage_ref, "agents": []},
            "execution": {"agent_mode": "sequential"},
            "error_handling": {"min_successful_agents": 1},
            "quality_gates": {"enabled": False},
        }


# Pre-configured realistic loader with common agents and stages
REALISTIC_CONFIG_LOADER = RealisticConfigLoader(
    agents={
        "research_agent": {"agent": REALISTIC_RESEARCH_AGENT.agent.model_dump()},
        "analyst_agent": {"agent": REALISTIC_ANALYST_AGENT.agent.model_dump()},
        "synthesis_agent": {"agent": REALISTIC_SYNTHESIS_AGENT.agent.model_dump()},
        "code_agent": {"agent": REALISTIC_CODE_AGENT.agent.model_dump()},
        "review_agent": {"agent": REALISTIC_REVIEW_AGENT.agent.model_dump()},
    },
    stages={
        "research": {
            "stage": {"name": "research", "agents": ["research_agent"]},
            "execution": {"agent_mode": "sequential"},
            "error_handling": {"min_successful_agents": 1},
            "quality_gates": {"enabled": False},
        },
        "analysis": {
            "stage": {"name": "analysis", "agents": ["analyst_agent"]},
            "execution": {"agent_mode": "sequential"},
            "error_handling": {"min_successful_agents": 1},
            "quality_gates": {"enabled": False},
        },
        "synthesis": {
            "stage": {"name": "synthesis", "agents": ["synthesis_agent"]},
            "execution": {"agent_mode": "sequential"},
            "error_handling": {"min_successful_agents": 1},
            "quality_gates": {"enabled": False},
        },
    },
)


def create_realistic_stage_config(
    name: str = "test_stage",
    agents: list[str] | None = None,
    agent_mode: str = "sequential",
    enable_synthesis: bool = False,
    enable_quality_gates: bool = False,
    min_successful_agents: int = 1,
) -> dict[str, Any]:
    """Create realistic stage configuration.

    Replaces manual dict creation with consistent, production-like configs.

    Args:
        name: Stage name
        agents: List of agent names (defaults to ["test_agent"])
        agent_mode: One of "sequential", "parallel", "adaptive"
        enable_synthesis: Enable collaboration/synthesis
        enable_quality_gates: Enable quality gates
        min_successful_agents: Minimum successful agents required

    Returns:
        Complete stage configuration dict

    Example:
        >>> config = create_realistic_stage_config(
        ...     name="parallel_stage",
        ...     agents=["agent1", "agent2"],
        ...     agent_mode="parallel",
        ...     enable_synthesis=True
        ... )
        >>> assert config["stage"]["name"] == "parallel_stage"
        >>> assert config["execution"]["agent_mode"] == "parallel"
    """
    agents = agents or ["test_agent"]

    config = {
        "stage": {"name": name, "agents": agents},
        "execution": {"agent_mode": agent_mode},
        "error_handling": {
            "min_successful_agents": min_successful_agents,
            "on_stage_failure": "halt",
        },
        "quality_gates": {"enabled": enable_quality_gates},
    }

    if enable_synthesis:
        config["collaboration"] = {"strategy": "consensus", "min_confidence": 0.7}

    return config


# Pre-configured stage configs for common scenarios
REALISTIC_SEQUENTIAL_STAGE_CONFIG = create_realistic_stage_config(
    name="sequential_stage", agents=["agent1", "agent2"], agent_mode="sequential"
)

REALISTIC_PARALLEL_STAGE_CONFIG = create_realistic_stage_config(
    name="parallel_stage",
    agents=["agent1", "agent2", "agent3"],
    agent_mode="parallel",
    enable_synthesis=True,
)

REALISTIC_ADAPTIVE_STAGE_CONFIG = create_realistic_stage_config(
    name="adaptive_stage",
    agents=["agent1", "agent2", "agent3"],
    agent_mode="adaptive",
    enable_synthesis=True,
)


# ==============================================================================
# TEST AGENT CLASS - Replaces mock agents with deterministic behavior
# ==============================================================================


class TestAgent:
    """Deterministic test agent with no LLM calls.

    Replaces mock agents with realistic behavior.
    Use for integration tests where agent execution is needed without actual LLM calls.

    Example:
        >>> agent = TestAgent("test_agent", output_template="Result: {input}")
        >>> response = agent.execute({"input": "test data"})
        >>> assert response["output"] == "Result: test data"
        >>> assert response["confidence"] == 0.85
    """

    def __init__(
        self,
        name: str,
        output_template: str | None = None,
        confidence: float = 0.85,
        reasoning_template: str | None = None,
    ):
        """Initialize test agent.

        Args:
            name: Agent name
            output_template: Template for output formatting (can use {input} and other keys)
            confidence: Confidence score for responses
            reasoning_template: Template for reasoning (optional)
        """
        self.name = name
        self.output_template = output_template or f"Output from {name}: {{input}}"
        self.reasoning_template = (
            reasoning_template or f"Deterministic reasoning from {name}"
        )
        self.confidence = confidence
        self.call_count = 0
        self.last_input: dict[str, Any] | None = None

    def execute(
        self, input_data: dict[str, Any], context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute with deterministic output - no LLM calls.

        Args:
            input_data: Input data dict (should have "input" key)
            context: Optional context data

        Returns:
            AgentResponse-like dict with output, reasoning, confidence, etc.
        """
        self.call_count += 1
        self.last_input = copy.deepcopy(input_data)

        # Format output based on template
        try:
            output = self.output_template.format(
                input=input_data.get("input", ""), **input_data
            )
        except KeyError:
            # Fallback if template has keys not in input_data
            output = (
                f"Output from {self.name}: {input_data.get('input', str(input_data))}"
            )

        # Format reasoning
        try:
            reasoning = self.reasoning_template.format(
                input=input_data.get("input", ""), **input_data
            )
        except (KeyError, AttributeError):
            reasoning = self.reasoning_template

        return {
            "output": output,
            "reasoning": reasoning,
            "confidence": self.confidence,
            "tokens": 100 + len(output),
            "estimated_cost_usd": 0.001,
            "tool_calls": [],
            "metadata": {
                "agent": self.name,
                "test_mode": True,
                "call_count": self.call_count,
            },
        }


def create_test_agent(
    name: str, output: str | None = None, confidence: float = 0.85
) -> TestAgent:
    """Create test agent with specific output.

    Args:
        name: Agent name
        output: Output template (defaults to "Output from {name}")
        confidence: Confidence score

    Returns:
        Configured TestAgent instance

    Example:
        >>> agent = create_test_agent("research", "Research result: {input}")
        >>> response = agent.execute({"input": "query"})
        >>> assert "Research result: query" in response["output"]
    """
    return TestAgent(name, output or f"Output from {name}", confidence)


def create_research_test_agent() -> TestAgent:
    """Create research agent for testing.

    Returns:
        TestAgent configured for research tasks
    """
    return TestAgent(
        "research_agent",
        "Research findings: {input}. Based on 12 sources with high confidence.",
        confidence=0.92,
        reasoning_template="Analyzed multiple sources and synthesized key findings",
    )


def create_analyst_test_agent() -> TestAgent:
    """Create analyst agent for testing.

    Returns:
        TestAgent configured for analysis tasks
    """
    return TestAgent(
        "analyst_agent",
        "Analysis: {input}. Key patterns identified with statistical significance.",
        confidence=0.88,
        reasoning_template="Applied statistical analysis to identify trends",
    )


def create_synthesis_test_agent() -> TestAgent:
    """Create synthesis agent for testing.

    Returns:
        TestAgent configured for synthesis tasks
    """
    return TestAgent(
        "synthesis_agent",
        "Synthesis: {input}. Combined insights into actionable recommendations.",
        confidence=0.90,
        reasoning_template="Synthesized findings from research and analysis phases",
    )


# ==============================================================================
# SYNTHESIS RESULT FIXTURES - Replaces manual SynthesisResult creation
# ==============================================================================


def create_synthesis_result(
    decision: str = "Approach A",
    confidence: float = 0.85,
    method: str = "consensus",
    votes: dict[str, int] | None = None,
    conflicts: list | None = None,
    reasoning: str | None = None,
) -> dict[str, Any]:
    """Create realistic SynthesisResult for testing.

    Args:
        decision: The synthesized decision
        confidence: Confidence score
        method: Synthesis method used
        votes: Vote distribution
        conflicts: List of conflicts
        reasoning: Reasoning for decision

    Returns:
        SynthesisResult-like dict

    Example:
        >>> result = create_synthesis_result("Use PostgreSQL", confidence=0.92)
        >>> assert result["decision"] == "Use PostgreSQL"
        >>> assert result["confidence"] == 0.92
    """
    votes = votes or {decision: 3}
    conflicts = conflicts or []
    reasoning = (
        reasoning
        or f"Synthesized decision: {decision} based on {sum(votes.values())} agent votes"
    )

    return {
        "decision": decision,
        "confidence": confidence,
        "method": method,
        "votes": votes,
        "conflicts": conflicts,
        "reasoning": reasoning,
        "metadata": {"test_mode": True},
    }


# Pre-configured synthesis results for common scenarios
REALISTIC_UNANIMOUS_SYNTHESIS = create_synthesis_result(
    decision="Approach A",
    confidence=0.92,
    method="consensus",
    votes={"Approach A": 3},
    reasoning="All agents agree on Approach A with high confidence",
)

REALISTIC_MAJORITY_SYNTHESIS = create_synthesis_result(
    decision="Approach A",
    confidence=0.80,
    method="majority_vote",
    votes={"Approach A": 2, "Approach B": 1},
    reasoning="Majority of agents support Approach A",
)

REALISTIC_SPLIT_SYNTHESIS = create_synthesis_result(
    decision="Approach A",
    confidence=0.65,
    method="weighted_vote",
    votes={"Approach A": 1, "Approach B": 1, "Approach C": 1},
    conflicts=["No clear consensus", "Conflicting priorities"],
    reasoning="Split decision resolved by weighted voting",
)
