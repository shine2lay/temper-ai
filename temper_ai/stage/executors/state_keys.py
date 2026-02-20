"""Constants for executor state dictionary keys.

This module defines constants for all state dictionary keys used across
executor implementations to eliminate magic strings and improve maintainability.
"""


class StateKeys:
    """State dictionary keys used across executor implementations.

    These constants replace magic strings for accessing state dictionaries
    in sequential, parallel, and adaptive executors.
    """

    # Top-level state keys
    STAGE_OUTPUTS = "stage_outputs"
    CURRENT_STAGE = "current_stage"
    WORKFLOW_ID = "workflow_id"
    WORKFLOW_INPUTS = "workflow_inputs"
    TRACKER = "tracker"
    TOOL_REGISTRY = "tool_registry"
    CONFIG_LOADER = "config_loader"
    VISUALIZER = "visualizer"
    SHOW_DETAILS = "show_details"
    DETAIL_CONSOLE = "detail_console"
    TOOL_EXECUTOR = "tool_executor"
    STREAM_CALLBACK = "stream_callback"
    TOTAL_STAGES = "total_stages"

    # Agent result keys
    AGENT_NAME = "agent_name"
    OUTPUT_DATA = "output_data"
    STATUS = "status"
    METRICS = "metrics"

    # Parallel execution state keys
    AGENT_OUTPUTS = "agent_outputs"
    AGENT_STATUSES = "agent_statuses"
    AGENT_METRICS = "agent_metrics"
    ERRORS = "errors"
    STAGE_INPUT = "stage_input"

    # Output data sub-keys
    OUTPUT = "output"
    ERROR = "error"
    ERROR_TYPE = "error_type"
    TRACEBACK = "traceback"
    REASONING = "reasoning"
    CONFIDENCE = "confidence"
    TOKENS = "tokens"
    COST_USD = "cost_usd"
    TOOL_CALLS = "tool_calls"

    # Metrics sub-keys
    DURATION_SECONDS = "duration_seconds"
    RETRIES = "retries"

    # Stage output sub-keys
    DECISION = "decision"
    STAGE_STATUS = "stage_status"
    SYNTHESIS = "synthesis"
    AGGREGATE_METRICS = "aggregate_metrics"

    # Retry tracking
    STAGE_RETRY_COUNTS = "stage_retry_counts"

    # Loop tracking (conditional stages)
    STAGE_LOOP_COUNTS = "stage_loop_counts"

    # Conversation history for stage:agent re-invocations
    CONVERSATION_HISTORIES = "conversation_histories"

    # Synthesis sub-keys
    METHOD = "method"
    VOTES = "votes"
    CONFLICTS = "conflicts"

    # Quality gate sub-keys
    QUALITY_GATE_WARNING = "quality_gate_warning"
    VIOLATIONS = "violations"

    # Aggregate metrics sub-keys
    TOTAL_TOKENS = "total_tokens"
    TOTAL_COST_USD = "total_cost_usd"
    TOTAL_DURATION_SECONDS = "total_duration_seconds"
    AVG_CONFIDENCE = "avg_confidence"
    NUM_AGENTS = "num_agents"
    NUM_SUCCESSFUL = "num_successful"
    NUM_FAILED = "num_failed"

    # Special markers
    AGGREGATE_METRICS_KEY = "__aggregate_metrics__"
    SKIP_TO_END = "_skip_to_end"
    DYNAMIC_INPUTS = "_dynamic_inputs"

    # Stage-specific keys
    CURRENT_STAGE_ID = "current_stage_id"
    CURRENT_STAGE_AGENTS = "current_stage_agents"
    MODE_SWITCH = "mode_switch"

    # Workflow-level rate limiter (R0.9)
    WORKFLOW_RATE_LIMITER = "workflow_rate_limiter"

    # Checkpoint resume: set of stage names already completed (R0.6)
    RESUMED_STAGES = "resumed_stages"

    # Frozenset constants for filtering non-serializable and reserved keys
    NON_SERIALIZABLE_KEYS: "frozenset[str]" = frozenset({
        "tracker", "tool_registry", "config_loader", "visualizer",
        "show_details", "detail_console", "tool_executor", "stream_callback",
        "total_stages",
    })

    RESERVED_UNWRAP_KEYS: "frozenset[str]" = frozenset({
        "stage_outputs", "current_stage", "workflow_id", "tracker",
        "tool_registry", "config_loader", "visualizer", "show_details",
        "detail_console", "workflow_inputs", "tool_executor", "stream_callback",
        "total_stages",
    })
