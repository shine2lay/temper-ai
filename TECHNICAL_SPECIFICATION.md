# Meta-Autonomous Agent Framework - Technical Specification

**Version:** 1.0
**Date:** 2026-01-25
**Status:** Technical Design Document

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Configuration System](#configuration-system)
3. [Agent Configuration Schema](#agent-configuration-schema)
4. [Tool Configuration Schema](#tool-configuration-schema)
5. [Stage Configuration Schema](#stage-configuration-schema)
6. [Workflow Configuration Schema](#workflow-configuration-schema)
7. [Trigger Configuration Schema](#trigger-configuration-schema)
8. [Observability System](#observability-system)
9. [Execution Engine](#execution-engine)
10. [M3 Multi-Agent Collaboration](#m3-multi-agent-collaboration)
11. [Safety System](#safety-system)
12. [Complete Examples](#complete-examples)

---

## Architecture Overview

### Three-Layer Configuration System

```
~/meta-autonomous-framework/
└── configs/
    ├── agents/              # Agent definitions (who does the work)
    │   ├── market_researcher.yaml
    │   ├── code_generator.yaml
    │   └── pm_agent.yaml
    │
    ├── stages/              # Stage definitions (what work gets done)
    │   ├── research_stage.yaml
    │   ├── build_stage.yaml
    │   └── analytics_stage.yaml
    │
    ├── workflows/           # Workflow definitions (how stages connect)
    │   ├── mvp_lifecycle.yaml
    │   ├── enterprise_lifecycle.yaml
    │   └── continuous_improvement.yaml
    │
    ├── tools/               # Tool definitions (capabilities)
    │   ├── web_scraper.yaml
    │   ├── file_writer.yaml
    │   └── git_client.yaml
    │
    ├── prompts/             # Reusable prompt templates
    │   ├── researcher_base.txt
    │   └── builder_base.txt
    │
    └── triggers/            # Workflow activation (when to start)
        ├── feedback_processor.yaml
        └── weekly_optimization.yaml
```

### Execution Flow

```
Trigger Activated
    ↓
Load Workflow Config (YAML)
    ↓
Compile to LangGraph
    ↓
For each Stage:
    ↓
    Load Stage Config → Load Agent Configs
    ↓
    Compile Stage to LangGraph (nested graph)
    ↓
    Phase 1: Parallel Agent Execution
        ├─ Agent A instantiated from config
        ├─ Agent B instantiated from config
        └─ Agent C instantiated from config
    ↓
    Phase 2: Synthesis/Collaboration
        ├─ Share agent outputs
        ├─ Apply collaboration strategy module
        ├─ Resolve conflicts via resolution strategy
        └─ Produce unified output
    ↓
    Pass output to next stage
    ↓
Workflow Complete
    ↓
Record full trace to SQLite/Postgres
```

### Technology Stack

- **Config Format:** YAML (primary), JSON (supported)
- **Execution Engine:** LangGraph (nested graphs)
- **Compiler:** YAMLToLangGraph compiler
- **Observability:** SQLite (dev) → Postgres (production)
- **Console UI:** Rich library (Python waterfall visualization)
- **Inference:** Multi-provider support (vLLM, Ollama, OpenAI, Anthropic)
- **Language:** Python 3.11+

---

## Configuration System

### Design Decisions

1. **YAML Primary, JSON Supported**
   - YAML: Human-friendly, comments, less verbose
   - JSON: Programmatic generation, strict validation

2. **Template-Based Prompts**
   - Reusable prompt templates with variable substitution
   - Enables A/B testing of prompts

3. **Tool Config with Overrides**
   - Default configs in tools/
   - Per-agent overrides allowed

4. **Modular Everything**
   - Collaboration strategies as modules
   - Conflict resolution as modules
   - Error handling as modules
   - Safety composition as modules

### Configuration Validation

All configs validated against JSON schemas on load:
- Type checking
- Required fields
- Enum validation
- Cross-references validated at runtime

---

## Agent Configuration Schema

**File Location:** `configs/agents/{agent_name}.yaml`

```yaml
agent:
  # ============================================
  # IDENTITY
  # ============================================
  name: market_researcher
  description: "Analyzes market trends and competitive landscape"
  version: "1.0"

  # ============================================
  # PROMPT CONFIGURATION
  # ============================================
  prompt:
    # Option 1: Template with variables (recommended for reusability)
    template: prompts/researcher_base.txt
    variables:
      domain: "SaaS products"
      tone: "analytical and data-driven"
      constraints: "Focus on B2B markets only"
      output_format: "structured markdown with bullet points"

    # Option 2: Inline string (for simple, one-off prompts)
    # inline: "You are a market researcher..."

  # ============================================
  # INFERENCE CONFIGURATION
  # ============================================
  inference:
    provider: ollama  # ollama | vllm | openai | anthropic | custom
    model: llama3.2:3b
    base_url: http://localhost:11434
    api_key: ${PROVIDER_API_KEY}  # Environment variable reference

    # Generation parameters
    temperature: 0.7
    max_tokens: 2048
    top_p: 0.9
    timeout_seconds: 60

    # Retry configuration
    max_retries: 3
    retry_delay_seconds: 2

  # ============================================
  # TOOL CONFIGURATION
  # ============================================
  tools:
    # Simple reference (uses default config from tools/)
    - WebScraper
    - Calculator

    # With per-agent overrides
    - name: DatabaseQuery
      config:
        max_rows: 1000
        timeout_seconds: 30
        connection_pool_size: 5

    - name: GoogleTrends
      config:
        regions: ["US", "EU", "APAC"]
        timeframe: "last_30_days"
        categories: ["Software", "SaaS"]

  # ============================================
  # SAFETY CONFIGURATION
  # ============================================
  safety:
    mode: execute  # execute | dry_run | require_approval
    require_approval_for_tools: []  # List of tool names needing approval
    max_tool_calls_per_execution: 20
    max_execution_time_seconds: 300
    risk_level: medium  # low | medium | high (affects safety composition)

  # ============================================
  # MEMORY CONFIGURATION
  # ============================================
  memory:
    enabled: false  # Set true when memory system implemented
    type: vector    # vector | episodic | procedural | semantic
    scope: session  # session | project | cross_session | permanent

    # Vector memory config
    retrieval_k: 10
    relevance_threshold: 0.7
    embedding_model: "sentence-transformers/all-MiniLM-L6-v2"

    # Episodic memory config
    max_episodes: 1000
    decay_factor: 0.95

  # ============================================
  # ERROR HANDLING
  # ============================================
  error_handling:
    retry_strategy: ExponentialBackoff  # Module reference
    max_retries: 3
    fallback: GracefulDegradation  # Module reference
    escalate_to_human_after: 3

    # Retry strategy config
    retry_config:
      initial_delay_seconds: 1
      max_delay_seconds: 30
      exponential_base: 2

  # ============================================
  # MERIT TRACKING
  # ============================================
  merit_tracking:
    enabled: true
    track_decision_outcomes: true
    domain_expertise: ["market_analysis", "competitive_research", "user_research"]

    # Merit decay config
    decay_enabled: true
    half_life_days: 90  # Merit halves every 90 days

  # ============================================
  # OBSERVABILITY
  # ============================================
  observability:
    log_inputs: true
    log_outputs: true
    log_reasoning: true
    log_full_llm_responses: false  # Just summary to save space
    track_latency: true
    track_token_usage: true

  # ============================================
  # METADATA
  # ============================================
  metadata:
    tags: ["research", "market", "external_data"]
    owner: "product_team"
    created: "2026-01-25"
    last_modified: "2026-01-25"
    documentation_url: "https://wiki.company.com/agents/market-researcher"
```

---

## Tool Configuration Schema

**File Location:** `configs/tools/{tool_name}.yaml`

```yaml
tool:
  # ============================================
  # IDENTITY
  # ============================================
  name: WebScraper
  description: "Scrapes web pages and extracts structured data"
  version: "2.1"
  category: "data_collection"

  # ============================================
  # IMPLEMENTATION
  # ============================================
  implementation: src.tools.web.WebScraperTool  # Python class path

  # ============================================
  # DEFAULT PARAMETERS
  # ============================================
  default_config:
    max_pages: 10
    timeout_seconds: 30
    follow_redirects: true
    max_redirects: 5
    user_agent: "MetaAutonomousAgent/1.0"
    respect_robots_txt: true

    # Parsing config
    extract_text: true
    extract_links: true
    extract_images: false
    extract_metadata: true

  # ============================================
  # SAFETY CHECKS
  # ============================================
  safety_checks:
    - PathTraversalPrevention

    - RateLimitEnforcement:
        max_requests_per_minute: 60
        max_requests_per_hour: 1000

    - ForbiddenDomains:
        blocked:
          - "facebook.com"  # Use API instead
          - "twitter.com"   # Use API instead
          - "linkedin.com"  # ToS violation

    - ContentSizeLimit:
        max_bytes: 10485760  # 10MB
        action_on_exceed: truncate  # truncate | fail

    - SecurityValidation:
        check_ssl_certs: true
        block_internal_ips: true  # Prevent SSRF

  # ============================================
  # RATE LIMITS
  # ============================================
  rate_limits:
    max_calls_per_minute: 100
    max_calls_per_hour: 1000
    max_concurrent_requests: 10
    cooldown_on_failure_seconds: 60

  # ============================================
  # ERROR HANDLING
  # ============================================
  error_handling:
    retry_on_status_codes: [429, 503, 504]
    max_retries: 3
    backoff_strategy: ExponentialBackoff
    timeout_is_retry: false  # Don't retry on timeout

  # ============================================
  # OBSERVABILITY
  # ============================================
  observability:
    log_inputs: true
    log_outputs: true
    log_full_response: false  # Summary only
    track_latency: true
    track_success_rate: true

    # Metrics
    metrics:
      - response_time_p50
      - response_time_p95
      - success_rate
      - error_rate_by_code

  # ============================================
  # REQUIREMENTS
  # ============================================
  requirements:
    requires_network: true
    requires_credentials: false
    requires_sandbox: false  # Set true if executing untrusted code

  # ============================================
  # METADATA
  # ============================================
  metadata:
    tags: ["web", "scraping", "external", "read_only"]
    documentation_url: "https://docs.company.com/tools/web-scraper"
    support_contact: "tools-team@company.com"
```

---

## Stage Configuration Schema

**File Location:** `configs/stages/{stage_name}.yaml`

```yaml
stage:
  # ============================================
  # IDENTITY
  # ============================================
  name: research
  description: "Multi-agent market and competitive research stage"
  version: "1.0"

  # ============================================
  # AGENTS
  # ============================================
  agents:
    - market_researcher      # Reference to agent config
    - competitor_analyst
    - user_research_agent

  # ============================================
  # INPUT/OUTPUT SCHEMA
  # ============================================
  inputs:
    # Flexible, self-normalizing (agents adapt to inputs)
    goal: Any
    vision_doc: Any
    constraints: Optional[Any]
    context: Optional[Dict]

  outputs:
    # Expected output structure
    research_report: Dict
    key_findings: List
    recommendations: List
    confidence_scores: Dict

  # ============================================
  # EXECUTION CONFIGURATION
  # ============================================
  execution:
    agent_mode: parallel  # parallel | sequential | adaptive
    timeout_seconds: 600

    # Adaptive mode config (if mode=adaptive)
    adaptive_config:
      start_parallel: true
      switch_to_sequential_if: "disagreement_rate > 0.5"

  # ============================================
  # COLLABORATION CONFIGURATION
  # ============================================
  collaboration:
    strategy: DebateAndSynthesize  # Module reference
    max_rounds: 3
    convergence_threshold: 0.8

    # Strategy-specific config
    config:
      debate_structure: "round_robin"  # round_robin | simultaneous | hierarchical
      synthesis_method: "consensus_extraction"  # consensus | weighted_merge | best_of
      allow_interruptions: false
      require_justifications: true

  # ============================================
  # CONFLICT RESOLUTION
  # ============================================
  conflict_resolution:
    strategy: MeritWeighted  # Module reference

    # Strategy-specific config
    config:
      metrics:
        - past_decision_outcomes
        - domain_expertise
        - context_relevance
        - recent_performance

      # Weights for each metric
      metric_weights:
        past_decision_outcomes: 0.4
        domain_expertise: 0.3
        context_relevance: 0.2
        recent_performance: 0.1

      min_confidence_to_auto_resolve: 0.85
      escalate_to_human_threshold: 0.5

      # Fallback if merit-based fails
      fallback: HumanEscalation

  # ============================================
  # SAFETY CONFIGURATION
  # ============================================
  safety:
    mode: execute  # Can override workflow-level
    dry_run_first: false
    require_approval: false

    # Conditional approval
    approval_required_when:
      - condition: "agent_disagrees_with_vision"
        threshold: 0.7
      - condition: "confidence_below"
        threshold: 0.6
      - condition: "high_risk_action_detected"

  # ============================================
  # ERROR HANDLING
  # ============================================
  error_handling:
    on_agent_failure: continue_with_remaining  # halt_stage | retry_agent | skip_agent
    min_successful_agents: 2  # Need at least N agents to succeed
    fallback_strategy: BestEffortSynthesis  # Module reference

    # Retry config for individual agents
    retry_failed_agents: true
    max_agent_retries: 2

  # ============================================
  # QUALITY GATES
  # ============================================
  quality_gates:
    enabled: true
    min_confidence: 0.7
    min_findings: 5
    require_citations: true

    # Action if quality gates fail
    on_failure: retry_stage  # retry_stage | escalate | proceed_with_warning

  # ============================================
  # METADATA
  # ============================================
  metadata:
    tags: ["research", "parallel", "external_data"]
    estimated_duration_seconds: 300
    cost_estimate_usd: 0.50
    requires_network: true
```

---

## Workflow Configuration Schema

**File Location:** `configs/workflows/{workflow_name}.yaml`

```yaml
workflow:
  # ============================================
  # IDENTITY
  # ============================================
  name: mvp_lifecycle
  description: "Rapid MVP development lifecycle for startups"
  version: "1.0"
  product_type: web_app  # web_app | mobile_app | api | data_product

  # ============================================
  # STAGES
  # ============================================
  stages:
    - name: research
      stage_ref: research_stage  # Reference to stage config
      depends_on: []  # No dependencies

    - name: requirements
      stage_ref: requirements_stage
      depends_on: [research]

    - name: design
      stage_ref: design_stage
      depends_on: [requirements]
      optional: true  # Can skip based on conditions
      skip_if: "project_duration < 7_days"

    - name: build
      stage_ref: build_stage
      depends_on: [design, requirements]  # Parallel dependencies

    - name: test
      stage_ref: test_stage
      depends_on: [build]

    - name: deploy
      stage_ref: deploy_stage
      depends_on: [test]
      conditional: true  # Only run if condition met
      condition: "test_coverage >= 0.8 AND test_pass_rate >= 0.95"

    - name: analytics
      stage_ref: analytics_stage
      depends_on: [deploy]

    - name: improve
      stage_ref: improvement_stage
      depends_on: [analytics]
      loops_back_to: research  # Create feedback loop
      max_loops: 5

  # ============================================
  # GLOBAL CONFIGURATION
  # ============================================
  config:
    max_iterations: 5  # For looping workflows
    convergence_detection: false  # Phase 1: fixed sequence, Phase 2: convergence
    timeout_seconds: 3600

    # Budget enforcement
    budget:
      max_cost_usd: 100
      max_tokens: 1000000
      action_on_exceed: halt  # halt | continue | notify

  # ============================================
  # SAFETY CONFIGURATION
  # ============================================
  safety:
    # Composition strategy (how to combine multi-layer safety rules)
    composition_strategy: MostRestrictive  # Module reference

    # Global defaults
    global_mode: execute  # execute | dry_run | require_approval

    # Stage-specific overrides
    approval_required_stages:
      - deploy
      - database_migration

    dry_run_stages:
      - build  # Always dry-run build first

    # Custom rules (evaluated in order)
    custom_rules:
      - if: "stage.name == 'deploy' AND env == 'production'"
        then: require_approval_and_dry_run

      - if: "agent.risk_level == 'high'"
        then: require_approval_for_all_tools

      - if: "workflow.cost_estimate > 50"
        then: require_budget_approval

  # ============================================
  # OPTIMIZATION TARGET
  # ============================================
  optimization:
    current_phase: growth  # growth | retention | efficiency | quality

    # Primary metric for improvement decisions
    primary_metric: user_activation

    # Secondary metrics (tracked but not optimized)
    secondary_metrics:
      - feature_adoption
      - error_rate
      - latency_p95
      - cost_per_user

    # Metric thresholds
    thresholds:
      user_activation:
        target: 0.7
        minimum: 0.5
      error_rate:
        target: 0.01
        maximum: 0.05

  # ============================================
  # OBSERVABILITY
  # ============================================
  observability:
    console_mode: standard  # minimal | standard | verbose
    trace_everything: true
    export_format:
      - json
      - sqlite

    # Visualization
    generate_dag_visualization: true
    waterfall_in_console: true

    # Alerting
    alert_on:
      - workflow_failure
      - stage_timeout
      - quality_gate_failure
      - budget_exceeded

  # ============================================
  # ERROR HANDLING
  # ============================================
  error_handling:
    on_stage_failure: halt  # halt | skip | retry
    max_stage_retries: 2
    escalation_policy: HumanReview  # Module reference

    # Rollback config
    enable_rollback: true
    rollback_on:
      - deployment_failure
      - quality_degradation
      - user_override_rate_spike

  # ============================================
  # METADATA
  # ============================================
  metadata:
    tags: ["mvp", "startup", "rapid"]
    target_environment: development  # development | staging | production
    owner: "engineering_team"
    documentation_url: "https://wiki.company.com/workflows/mvp-lifecycle"
    created: "2026-01-25"
    last_modified: "2026-01-25"
```

---

## Trigger Configuration Schema

**File Location:** `configs/triggers/{trigger_name}.yaml`

### Event-Based Trigger

```yaml
trigger:
  # ============================================
  # IDENTITY
  # ============================================
  name: feedback_processor
  description: "Processes new user feedback and triggers improvement cycle"
  type: EventTrigger  # EventTrigger | CronTrigger | ThresholdTrigger | ManualTrigger

  # ============================================
  # EVENT SOURCE CONFIGURATION
  # ============================================
  source:
    type: message_queue  # message_queue | webhook | database_poll | file_watch

    # Message queue config
    connection: ${RABBITMQ_URL}
    queue_name: user_feedback
    consumer_group: feedback_processors

    # Connection pool
    max_connections: 10
    reconnect_delay_seconds: 5

  # ============================================
  # FILTERING
  # ============================================
  filter:
    event_type: new_feedback

    # Conditions (all must match)
    conditions:
      - field: sentiment
        operator: in
        values: [negative, neutral]

      - field: category
        operator: in
        values: [feature_request, bug_report, performance]

      - field: user_tier
        operator: in
        values: [paid, enterprise]  # Prioritize paying customers

  # ============================================
  # WORKFLOW INVOCATION
  # ============================================
  workflow: feedback_to_improvement_workflow

  # Input mapping (from event to workflow inputs)
  workflow_inputs:
    feedback_text: ${event.body.text}
    user_id: ${event.body.user_id}
    feedback_category: ${event.body.category}
    timestamp: ${event.timestamp}
    metadata: ${event.metadata}

  # ============================================
  # CONCURRENCY CONTROL
  # ============================================
  concurrency:
    max_parallel_executions: 5
    queue_when_busy: true
    max_queue_size: 100

    # Deduplication
    deduplicate: true
    dedup_window_seconds: 300
    dedup_key: ${event.body.user_id}_${event.body.text}

  # ============================================
  # RETRY CONFIGURATION
  # ============================================
  retry:
    enabled: true
    max_retries: 3
    retry_delay_seconds: 60
    exponential_backoff: true

  # ============================================
  # METADATA
  # ============================================
  metadata:
    owner: "product_team"
    alert_on_failure: true
    alert_channels: ["slack", "pagerduty"]
```

### Cron-Based Trigger

```yaml
trigger:
  name: weekly_optimization
  description: "Weekly analysis and optimization of system performance"
  type: CronTrigger

  # ============================================
  # SCHEDULE
  # ============================================
  schedule: "0 0 * * 0"  # Sunday midnight (cron format)
  timezone: UTC

  # Skip execution if
  skip_on_holiday: true
  skip_if_recent_execution: true
  min_hours_between_runs: 168  # 1 week

  # ============================================
  # WORKFLOW INVOCATION
  # ============================================
  workflow: analyze_and_optimize_workflow

  workflow_inputs:
    lookback_days: 7
    optimization_target: ${CURRENT_OPTIMIZATION_TARGET}
    generate_report: true

  # ============================================
  # METADATA
  # ============================================
  metadata:
    owner: "platform_team"
    notify_on_completion: true
    notification_channels: ["email", "slack"]
```

### Threshold-Based Trigger

```yaml
trigger:
  name: error_rate_alert
  description: "Triggers incident response when error rate exceeds threshold"
  type: ThresholdTrigger

  # ============================================
  # METRIC MONITORING
  # ============================================
  metric:
    source: prometheus  # prometheus | datadog | custom | database
    query: "rate(http_errors_total[5m])"
    evaluation_interval_seconds: 60

  # ============================================
  # CONDITION
  # ============================================
  condition: greater_than
  threshold: 0.05  # 5% error rate
  duration_minutes: 10  # Must be above threshold for this long

  # Multiple condition support
  compound_conditions:
    operator: AND
    conditions:
      - metric: "error_rate"
        operator: ">"
        value: 0.05
      - metric: "request_volume"
        operator: ">"
        value: 100  # Only alert if significant traffic

  # ============================================
  # WORKFLOW INVOCATION
  # ============================================
  workflow: incident_response_workflow

  workflow_inputs:
    alert_severity: high
    metric_name: "error_rate"
    metric_value: ${metric.current_value}
    threshold_exceeded: ${metric.threshold}
    duration_minutes: ${metric.duration_minutes}

  # ============================================
  # METADATA
  # ============================================
  metadata:
    owner: "sre_team"
    alert_immediately: true
    priority: critical
```

---

## Observability System

### Database Schema (SQLite/Postgres)

```sql
-- ============================================
-- WORKFLOW EXECUTIONS (Top Level)
-- ============================================
CREATE TABLE workflow_executions (
    id TEXT PRIMARY KEY,
    workflow_name TEXT NOT NULL,
    workflow_version TEXT,
    workflow_config_snapshot JSON NOT NULL,  -- Full config used

    -- Trigger info
    trigger_type TEXT,  -- cron | event | threshold | manual
    trigger_id TEXT,
    trigger_data JSON,

    -- Timing
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    duration_seconds REAL,

    -- Status
    status TEXT NOT NULL,  -- running | completed | failed | halted | timeout
    error_message TEXT,
    error_stack_trace TEXT,

    -- Context
    optimization_target TEXT,
    product_type TEXT,
    environment TEXT,  -- development | staging | production

    -- Metrics
    total_cost_usd REAL,
    total_tokens INTEGER,
    total_llm_calls INTEGER,
    total_tool_calls INTEGER,

    -- Metadata
    tags JSON,
    metadata JSON,

    -- Indexes
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_workflow_status ON workflow_executions(status, start_time);
CREATE INDEX idx_workflow_name ON workflow_executions(workflow_name, start_time);

-- ============================================
-- STAGE EXECUTIONS
-- ============================================
CREATE TABLE stage_executions (
    id TEXT PRIMARY KEY,
    workflow_execution_id TEXT NOT NULL REFERENCES workflow_executions(id),

    -- Identity
    stage_name TEXT NOT NULL,
    stage_version TEXT,
    stage_config_snapshot JSON NOT NULL,

    -- Timing
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    duration_seconds REAL,

    -- Status
    status TEXT NOT NULL,
    error_message TEXT,

    -- Data
    input_data JSON,  -- Full input to stage
    output_data JSON,  -- Full output from stage

    -- Metrics
    num_agents_executed INTEGER,
    num_agents_succeeded INTEGER,
    num_agents_failed INTEGER,
    collaboration_rounds INTEGER,

    -- Metadata
    metadata JSON
);

CREATE INDEX idx_stage_workflow ON stage_executions(workflow_execution_id, stage_name);
CREATE INDEX idx_stage_status ON stage_executions(status, start_time);

-- ============================================
-- AGENT EXECUTIONS
-- ============================================
CREATE TABLE agent_executions (
    id TEXT PRIMARY KEY,
    stage_execution_id TEXT NOT NULL REFERENCES stage_executions(id),

    -- Identity
    agent_name TEXT NOT NULL,
    agent_version TEXT,
    agent_config_snapshot JSON NOT NULL,

    -- Timing
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    duration_seconds REAL,

    -- Status
    status TEXT NOT NULL,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,

    -- Core data
    reasoning TEXT,  -- Why agent made decisions
    input_data JSON,  -- Full input to agent
    output_data JSON,  -- Full output from agent

    -- Performance metrics
    llm_duration_seconds REAL,
    tool_duration_seconds REAL,

    -- LLM metrics
    total_tokens INTEGER,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    estimated_cost_usd REAL,
    num_llm_calls INTEGER,

    -- Tool metrics
    num_tool_calls INTEGER,

    -- Collaboration data
    votes_cast JSON,  -- In synthesis phase
    conflicts_with_agents JSON,
    final_decision TEXT,
    confidence_score REAL,

    -- Quality metrics
    output_quality_score REAL,
    reasoning_quality_score REAL,

    -- Metadata
    metadata JSON
);

CREATE INDEX idx_agent_stage ON agent_executions(stage_execution_id, agent_name);
CREATE INDEX idx_agent_name ON agent_executions(agent_name, start_time);

-- ============================================
-- LLM CALLS (Detailed Tracking)
-- ============================================
CREATE TABLE llm_calls (
    id TEXT PRIMARY KEY,
    agent_execution_id TEXT NOT NULL REFERENCES agent_executions(id),

    -- Provider info
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    base_url TEXT,

    -- Timing
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    latency_ms INTEGER,

    -- Request/Response
    prompt TEXT,
    response TEXT,

    -- Token metrics
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,

    -- Cost
    estimated_cost_usd REAL,

    -- Parameters
    temperature REAL,
    max_tokens INTEGER,
    top_p REAL,

    -- Status
    status TEXT NOT NULL,  -- success | failed | timeout | rate_limited
    error_message TEXT,
    http_status_code INTEGER,

    -- Retry info
    retry_count INTEGER DEFAULT 0,

    -- Metadata
    metadata JSON
);

CREATE INDEX idx_llm_agent ON llm_calls(agent_execution_id, start_time);
CREATE INDEX idx_llm_model ON llm_calls(model, start_time);
CREATE INDEX idx_llm_status ON llm_calls(status, start_time);

-- ============================================
-- TOOL EXECUTIONS
-- ============================================
CREATE TABLE tool_executions (
    id TEXT PRIMARY KEY,
    agent_execution_id TEXT NOT NULL REFERENCES agent_executions(id),

    -- Tool info
    tool_name TEXT NOT NULL,
    tool_version TEXT,

    -- Timing
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    duration_seconds REAL,

    -- Input/Output
    input_params JSON,  -- Full parameters
    output_data JSON,  -- Full response

    -- Status
    status TEXT NOT NULL,  -- success | failed | timeout | rate_limited
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,

    -- Safety
    safety_checks_applied JSON,
    approval_required BOOLEAN,
    approved_by TEXT,
    approval_timestamp TIMESTAMP,

    -- Metadata
    metadata JSON
);

CREATE INDEX idx_tool_agent ON tool_executions(agent_execution_id, tool_name);
CREATE INDEX idx_tool_name ON tool_executions(tool_name, start_time);
CREATE INDEX idx_tool_status ON tool_executions(status, start_time);

-- ============================================
-- COLLABORATION EVENTS (Synthesis Phase)
-- ============================================
CREATE TABLE collaboration_events (
    id TEXT PRIMARY KEY,
    stage_execution_id TEXT NOT NULL REFERENCES stage_executions(id),

    -- Event type
    event_type TEXT NOT NULL,  -- vote | conflict | resolution | consensus | debate_round
    timestamp TIMESTAMP NOT NULL,
    round_number INTEGER,

    -- Participants
    agents_involved JSON,

    -- Data
    event_data JSON,  -- Votes, arguments, resolution details

    -- Outcome
    resolution_strategy TEXT,
    outcome TEXT,
    confidence_score REAL,

    -- Metadata
    metadata JSON
);

CREATE INDEX idx_collab_stage ON collaboration_events(stage_execution_id, event_type);

-- ============================================
-- MERIT SCORES (Reputation System)
-- ============================================
CREATE TABLE agent_merit_scores (
    id TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL,
    domain TEXT NOT NULL,  -- e.g., "market_research", "code_generation"

    -- Cumulative scores
    total_decisions INTEGER DEFAULT 0,
    successful_decisions INTEGER DEFAULT 0,
    failed_decisions INTEGER DEFAULT 0,
    overridden_decisions INTEGER DEFAULT 0,

    -- Calculated metrics
    success_rate REAL,
    average_confidence REAL,
    expertise_score REAL,  -- Calculated from outcomes

    -- Time-based metrics (with decay)
    last_30_days_success_rate REAL,
    last_90_days_success_rate REAL,

    -- Timestamps
    first_decision_date TIMESTAMP,
    last_decision_date TIMESTAMP,
    last_updated TIMESTAMP,

    -- Metadata
    metadata JSON,

    UNIQUE(agent_name, domain)
);

CREATE INDEX idx_merit_agent ON agent_merit_scores(agent_name, domain);
CREATE INDEX idx_merit_score ON agent_merit_scores(expertise_score DESC);

-- ============================================
-- DECISION OUTCOMES (Learning Loop)
-- ============================================
CREATE TABLE decision_outcomes (
    id TEXT PRIMARY KEY,
    agent_execution_id TEXT REFERENCES agent_executions(id),
    stage_execution_id TEXT REFERENCES stage_executions(id),
    workflow_execution_id TEXT REFERENCES workflow_executions(id),

    -- Decision info
    decision_type TEXT NOT NULL,  -- feature | bug_fix | optimization | config_change
    decision_data JSON NOT NULL,

    -- Validation
    validation_method TEXT,  -- a_b_test | metric_comparison | human_review | automated_test
    validation_timestamp TIMESTAMP,
    validation_duration_seconds REAL,

    -- Outcome
    outcome TEXT NOT NULL,  -- success | failure | neutral | mixed
    impact_metrics JSON,  -- Actual metric changes

    -- Learning
    lessons_learned TEXT,
    should_repeat BOOLEAN,
    tags JSON,

    -- Metadata
    metadata JSON
);

CREATE INDEX idx_outcome_agent ON decision_outcomes(agent_execution_id, outcome);
CREATE INDEX idx_outcome_type ON decision_outcomes(decision_type, outcome);
CREATE INDEX idx_outcome_validation ON decision_outcomes(validation_timestamp DESC);

-- ============================================
-- SYSTEM METRICS (Aggregated)
-- ============================================
CREATE TABLE system_metrics (
    id TEXT PRIMARY KEY,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    metric_unit TEXT,

    -- Dimensions
    workflow_name TEXT,
    stage_name TEXT,
    agent_name TEXT,
    environment TEXT,

    -- Time
    timestamp TIMESTAMP NOT NULL,
    aggregation_period TEXT,  -- minute | hour | day

    -- Metadata
    tags JSON,
    metadata JSON
);

CREATE INDEX idx_metrics_name ON system_metrics(metric_name, timestamp);
CREATE INDEX idx_metrics_workflow ON system_metrics(workflow_name, timestamp);
```

### Console Visualization

**Implementation using Rich library (Python):**

```python
from rich.tree import Tree
from rich.console import Console
from rich.table import Table
from rich import box

class WorkflowVisualizer:
    def __init__(self, verbosity="standard"):
        self.console = Console()
        self.verbosity = verbosity  # minimal | standard | verbose

    def display_execution(self, workflow_execution):
        """Display waterfall visualization"""

        # Create root tree
        tree = Tree(
            f"[bold cyan]Workflow: {workflow_execution.name}[/] "
            f"[dim]({workflow_execution.duration}s)[/]"
        )

        # Add stages
        for stage in workflow_execution.stages:
            stage_node = tree.add(
                f"[bold yellow]Stage: {stage.name}[/] "
                f"[dim]({stage.duration}s)[/] "
                f"{self._status_icon(stage.status)}"
            )

            if self.verbosity in ["standard", "verbose"]:
                # Add agents
                for agent in stage.agents:
                    agent_node = stage_node.add(
                        f"[green]Agent: {agent.name}[/] "
                        f"[dim]({agent.duration}s)[/] "
                        f"{self._status_icon(agent.status)}"
                    )

                    if self.verbosity == "verbose":
                        # Add LLM calls
                        for llm_call in agent.llm_calls:
                            agent_node.add(
                                f"[blue]LLM: {llm_call.model}[/] "
                                f"[dim]({llm_call.latency}ms, {llm_call.tokens} tokens)[/] "
                                f"{self._status_icon(llm_call.status)}"
                            )

                        # Add tool calls
                        for tool_call in agent.tool_calls:
                            agent_node.add(
                                f"[magenta]Tool: {tool_call.name}[/] "
                                f"[dim]({tool_call.duration}s)[/] "
                                f"{self._status_icon(tool_call.status)}"
                            )

                # Add synthesis
                if stage.synthesis:
                    synthesis_node = stage_node.add(
                        f"[cyan]Synthesis: {stage.synthesis.strategy}[/] "
                        f"[dim]({stage.synthesis.duration}s)[/] "
                        f"{self._status_icon(stage.synthesis.status)}"
                    )

                    if self.verbosity == "verbose" and stage.synthesis.votes:
                        for vote in stage.synthesis.votes:
                            synthesis_node.add(
                                f"[dim]Vote: {vote.agent} → {vote.decision} "
                                f"(confidence: {vote.confidence:.2f})[/]"
                            )

        self.console.print(tree)

    def _status_icon(self, status):
        """Return colored status icon"""
        icons = {
            "success": "[green]✓[/]",
            "failed": "[red]✗[/]",
            "running": "[yellow]⏳[/]",
            "timeout": "[red]⌛[/]",
            "dry_run": "[blue]⏸[/]",
        }
        return icons.get(status, "[dim]?[/]")
```

**Output Example (Standard Mode):**

```
Workflow: mvp_lifecycle (2.3s)
├─ Stage: research (0.8s) ✓
│  ├─ Agent: market_researcher (0.4s) ✓
│  ├─ Agent: competitor_analyst (0.3s) ✓
│  └─ Synthesis: consensus (0.1s) ✓
├─ Stage: requirements (1.2s) ✓
│  ├─ Agent: pm_agent (0.8s) ✓
│  └─ Agent: tech_lead (0.4s) ✓
└─ Stage: build (0.3s - DRY RUN) ⏸
   └─ Agent: code_generator (0.3s) ⏸
```

**Output Example (Verbose Mode):**

```
Workflow: mvp_lifecycle (2.3s)
├─ Stage: research (0.8s) ✓
│  ├─ Agent: market_researcher (0.4s) ✓
│  │  ├─ LLM: llama3.2:3b (250ms, 150 tokens) ✓
│  │  ├─ Tool: WebScraper (120ms) ✓
│  │  └─ LLM: llama3.2:3b (180ms, 80 tokens) ✓
│  ├─ Agent: competitor_analyst (0.3s) ✓
│  │  ├─ Tool: CompetitorAPI (200ms) ✓
│  │  └─ LLM: llama3.2:3b (100ms, 120 tokens) ✓
│  └─ Synthesis: consensus (0.1s) ✓
│     ├─ Vote: market_researcher → "focus on B2B" (confidence: 0.9)
│     ├─ Vote: competitor_analyst → "focus on B2B" (confidence: 0.8)
│     └─ Decision: "focus on B2B" (consensus: 0.85)
```

---

## Execution Engine

### Execution Engine Abstraction Layer

The framework uses an abstraction layer to decouple workflow execution from specific graph libraries. This enables vendor independence, experimentation with alternative engines, and support for advanced features in future milestones.

**Key Interfaces:**

- **ExecutionEngine:** Abstract base for all execution engines
- **CompiledWorkflow:** Abstract workflow representation
- **ExecutionMode:** Enum for execution modes (SYNC, ASYNC, STREAM)
- **EngineRegistry:** Factory for engine creation and selection

See [Execution Engine Architecture](./docs/features/execution/execution_engine_architecture.md) for complete details.

### ExecutionEngine Interface

**Location:** `src/compiler/execution_engine.py:115`

All execution engines must implement these methods:

#### compile(workflow_config: Dict) → CompiledWorkflow

Compiles workflow configuration into executable form.

- Validates config structure
- Optimizes workflow representation
- Returns engine-specific CompiledWorkflow

#### execute(compiled_workflow, input_data, mode=SYNC) → Dict

Executes compiled workflow with given input.

- Supports SYNC, ASYNC, and STREAM modes
- Returns final workflow state
- Maintains observability and safety

#### supports_feature(feature: str) → bool

Runtime capability detection for engine features.

**Standard features:**
- `sequential_stages`: Sequential stage execution
- `parallel_stages`: Parallel stage execution
- `conditional_routing`: Conditional transitions
- `convergence_detection`: Convergence detection (M5+)
- `dynamic_stage_injection`: Runtime stage injection (M5+)
- `nested_workflows`: Nested workflow support
- `checkpointing`: Save/restore execution state
- `state_persistence`: External state persistence
- `streaming_execution`: Stream intermediate results (M4+)
- `distributed_execution`: Distributed execution (M7+)

### CompiledWorkflow Interface

**Location:** `src/compiler/execution_engine.py:33`

Represents a compiled workflow in engine-specific format:

- **invoke(state):** Synchronous execution
- **ainvoke(state):** Asynchronous execution
- **get_metadata():** Workflow metadata (engine, version, config, stages)
- **visualize():** Visual representation (Mermaid, DOT, etc.)

### Engine Selection

Engines can be selected via workflow YAML configuration:

```yaml
workflow:
  name: my_workflow
  engine: langgraph  # or custom engine name
  engine_config:
    max_retries: 3
    timeout: 300
  stages: [...]
```

Or programmatically via EngineRegistry:

```python
from src.compiler.engine_registry import EngineRegistry

registry = EngineRegistry()

# Get engine by name
engine = registry.get_engine("langgraph")

# Or get from config
engine = registry.get_engine_from_config(workflow_config)
```

### Available Engines

**M2.5 - LangGraph (default):**
- Adapter wrapping existing LangGraphCompiler
- Supports sequential and parallel stages
- Full M2 backward compatibility
- 100% test pass rate maintained

**M5+ - Custom engines:**
- Convergence detection engine (planned)
- Dynamic workflow modification (planned)
- Meta-circular evaluation (planned)

**M6+ - Production engines:**
- Temporal Workflows for durable execution
- Ray DAGs for distributed execution

See [Custom Engine Guide](./docs/features/execution/custom_engine_guide.md) for implementation details.

### LangGraph Compiler Architecture

```python
from typing import Dict, Any, List
from langgraph.graph import StateGraph, END
from pydantic import BaseModel

class LifecycleCompiler:
    """
    Compiles YAML configurations into executable LangGraph workflows.

    Architecture:
    - Workflows compile to top-level LangGraph
    - Each stage compiles to nested LangGraph
    - Agents execute within stage graphs
    """

    def __init__(self, config_loader: ConfigLoader):
        self.config_loader = config_loader
        self.agent_registry = AgentRegistry()
        self.tool_registry = ToolRegistry()
        self.strategy_registry = StrategyRegistry()

    def compile_workflow(self, workflow_name: str) -> CompiledWorkflow:
        """
        Main entry point: Compile workflow YAML to executable LangGraph.

        Steps:
        1. Load workflow config
        2. Validate dependencies (all stages exist, no cycles)
        3. Create lifecycle state schema
        4. Build workflow graph
        5. Add stage nodes (each is a compiled stage graph)
        6. Add edges based on dependencies
        7. Add conditional routing
        8. Compile and return
        """
        # Load config
        workflow_config = self.config_loader.load_workflow(workflow_name)

        # Validate
        self._validate_workflow(workflow_config)

        # Create state
        lifecycle_state = self._create_lifecycle_state(workflow_config)

        # Build graph
        graph = StateGraph(lifecycle_state)

        # Add stage nodes
        for stage_config in workflow_config.stages:
            stage_graph = self._compile_stage(stage_config.stage_ref)
            graph.add_node(stage_config.name, stage_graph)

        # Add edges (dependencies)
        self._add_edges(graph, workflow_config.stages)

        # Add conditional edges (for optional/conditional stages)
        self._add_conditional_edges(graph, workflow_config.stages)

        # Compile
        compiled = graph.compile()

        return CompiledWorkflow(
            name=workflow_name,
            config=workflow_config,
            graph=compiled
        )

    def _compile_stage(self, stage_name: str) -> CompiledGraph:
        """
        Compile a single stage into nested LangGraph.

        Stage graph structure:
        - Start node
        - Parallel agent nodes (or sequential if configured)
        - Synthesis node (collaboration)
        - End node
        """
        # Load stage config
        stage_config = self.config_loader.load_stage(stage_name)

        # Create state
        stage_state = self._create_stage_state(stage_config)

        # Build graph
        graph = StateGraph(stage_state)

        # Add start node
        graph.add_node("start", self._stage_start_node)

        # Add agent nodes
        if stage_config.execution.agent_mode == "parallel":
            # Parallel execution
            for agent_name in stage_config.agents:
                agent = self._instantiate_agent(agent_name)
                graph.add_node(agent_name, agent.execute)
                graph.add_edge("start", agent_name)
        else:
            # Sequential execution
            prev_node = "start"
            for agent_name in stage_config.agents:
                agent = self._instantiate_agent(agent_name)
                graph.add_node(agent_name, agent.execute)
                graph.add_edge(prev_node, agent_name)
                prev_node = agent_name

        # Add synthesis node
        collaboration_strategy = self._get_collaboration_strategy(
            stage_config.collaboration.strategy
        )
        graph.add_node("synthesize", collaboration_strategy.synthesize)

        # Connect agents to synthesis
        for agent_name in stage_config.agents:
            graph.add_edge(agent_name, "synthesize")

        # Add end node
        graph.add_node("end", self._stage_end_node)
        graph.add_edge("synthesize", "end")
        graph.add_edge("end", END)

        return graph.compile()

    def _instantiate_agent(self, agent_name: str) -> Agent:
        """
        Load agent config and create executable agent instance.

        Steps:
        1. Load agent YAML
        2. Load prompt template
        3. Create LLM client
        4. Load and instantiate tools
        5. Apply safety wrappers
        6. Apply observability hooks
        7. Return wrapped agent
        """
        # Load config
        config = self.config_loader.load_agent(agent_name)

        # Load prompt
        if config.prompt.template:
            prompt = self._load_prompt_template(
                config.prompt.template,
                config.prompt.variables
            )
        else:
            prompt = config.prompt.inline

        # Create LLM
        llm = self._create_llm(config.inference)

        # Load tools
        tools = self._load_tools(config.tools)

        # Create agent
        agent = Agent(
            name=agent_name,
            prompt=prompt,
            llm=llm,
            tools=tools,
            config=config
        )

        # Apply wrappers (safety, observability, error handling)
        agent = self._apply_safety_wrapper(agent, config.safety)
        agent = self._apply_observability_wrapper(agent)
        agent = self._apply_error_handling_wrapper(agent, config.error_handling)

        return agent

    def _create_llm(self, inference_config: InferenceConfig) -> LLM:
        """Create LLM client based on provider"""
        providers = {
            "ollama": OllamaLLM,
            "vllm": VLLMLLM,
            "openai": OpenAILLM,
            "anthropic": AnthropicLLM,
        }

        llm_class = providers.get(inference_config.provider)
        if not llm_class:
            raise ValueError(f"Unknown provider: {inference_config.provider}")

        return llm_class(
            model=inference_config.model,
            base_url=inference_config.base_url,
            api_key=inference_config.api_key,
            temperature=inference_config.temperature,
            max_tokens=inference_config.max_tokens,
            timeout=inference_config.timeout_seconds
        )

    def _load_tools(self, tools_config: List[ToolRef]) -> List[Tool]:
        """Load and configure tools"""
        tools = []

        for tool_ref in tools_config:
            if isinstance(tool_ref, str):
                # Simple reference - use defaults
                tool_config = self.config_loader.load_tool(tool_ref)
                tool = self.tool_registry.get_tool(tool_ref)
            else:
                # With overrides
                tool_config = self.config_loader.load_tool(tool_ref.name)
                # Merge overrides
                tool_config = self._merge_tool_config(
                    tool_config,
                    tool_ref.config
                )
                tool = self.tool_registry.get_tool(tool_ref.name)

            # Configure tool
            tool.configure(tool_config)
            tools.append(tool)

        return tools

    def _get_collaboration_strategy(self, strategy_name: str) -> CollaborationStrategy:
        """Get collaboration strategy module"""
        return self.strategy_registry.get_strategy(strategy_name)
```

### State Management

```python
from typing import TypedDict, Dict, Any, List

class LifecycleState(TypedDict):
    """
    Top-level workflow state.

    Passed between stages, accumulates outputs.
    """
    # Identity
    workflow_id: str
    workflow_name: str
    execution_id: str

    # Progress
    current_stage: str
    completed_stages: List[str]

    # Data
    global_context: Dict[str, Any]
    stage_outputs: Dict[str, Any]  # stage_name → output

    # Quality
    quality_scores: Dict[str, float]
    confidence_scores: Dict[str, float]

    # Errors
    errors: List[Dict[str, Any]]
    warnings: List[str]

    # Metadata
    start_time: float
    metadata: Dict[str, Any]

class StageState(TypedDict):
    """
    Single stage state.

    Contains inputs, agent outputs, and synthesis result.
    """
    # Identity
    stage_id: str
    stage_name: str
    execution_id: str

    # Input
    inputs: Dict[str, Any]

    # Agent outputs
    agent_outputs: Dict[str, Any]  # agent_name → output
    agent_states: Dict[str, Dict]  # Full agent state

    # Synthesis
    synthesis_rounds: List[Dict]
    synthesis_result: Dict[str, Any]

    # Collaboration
    collaboration_log: List[Dict]
    conflicts: List[Dict]
    resolutions: List[Dict]

    # Quality
    output_quality: float
    confidence: float

    # Errors
    errors: List[Dict[str, Any]]

    # Metadata
    start_time: float
    metadata: Dict[str, Any]

class AgentState(TypedDict):
    """
    Single agent state.

    Tracks agent execution details.
    """
    # Identity
    agent_id: str
    agent_name: str
    execution_id: str

    # Input
    inputs: Dict[str, Any]

    # Reasoning
    reasoning: str
    decision_log: List[str]

    # Actions
    tool_calls: List[Dict]
    llm_calls: List[Dict]

    # Output
    output: Dict[str, Any]
    confidence: float

    # Quality
    output_quality: float
    reasoning_quality: float

    # Errors
    errors: List[Dict[str, Any]]

    # Metadata
    start_time: float
    metadata: Dict[str, Any]
```

---

## M3 Multi-Agent Collaboration

**Status:** 69% Complete (11/16 tasks)
**Performance:** 2-3x speedup with parallel execution
**Test Coverage:** 31/34 tests passing (91%)

### Overview

M3 introduces true multi-agent collaboration capabilities:
- **Parallel Execution:** Run multiple agents concurrently using LangGraph nested subgraphs
- **Collaboration Strategies:** Consensus, debate, merit-weighted synthesis
- **Conflict Resolution:** Automatic detection and resolution of disagreements
- **Convergence Detection:** Early termination when agents reach agreement
- **Quality Gates:** Validate synthesis outputs before proceeding

### Parallel Execution Architecture

#### LangGraph Nested Subgraphs

Parallel execution uses LangGraph's native support for parallel branches:

```python
from typing_extensions import Annotated, TypedDict
from langgraph.graph import StateGraph, END

# Custom dict merger for concurrent updates
def merge_dicts(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    """Merge two dicts for concurrent agent outputs."""
    result = left.copy() if left else {}
    result.update(right)
    return result

# Parallel stage state
class ParallelStageState(TypedDict, total=False):
    agent_outputs: Annotated[Dict[str, Any], merge_dicts]
    agent_statuses: Annotated[Dict[str, str], merge_dicts]
    errors: Annotated[Dict[str, str], merge_dicts]
    stage_input: Dict[str, Any]

# Create parallel subgraph
def _execute_parallel_stage(stage_config, agents):
    """Execute agents in parallel using nested LangGraph."""

    # Create subgraph
    subgraph = StateGraph(ParallelStageState)

    # Add parallel agent nodes
    for agent_cfg in agents:
        agent_node = _create_agent_node(agent_cfg)
        subgraph.add_node(f"agent_{agent_cfg['name']}", agent_node)

    # Add synthesis node
    subgraph.add_node("synthesis", _run_synthesis)

    # Parallel edges: all agents execute concurrently
    for agent_cfg in agents:
        subgraph.add_edge(START, f"agent_{agent_cfg['name']}")
        subgraph.add_edge(f"agent_{agent_cfg['name']}", "synthesis")

    subgraph.add_edge("synthesis", END)

    return subgraph.compile()
```

#### Agent Execution Node

```python
def _create_agent_node(agent_config: Dict[str, Any]):
    """Create individual agent execution node."""

    def agent_node(state: ParallelStageState) -> Dict[str, Any]:
        agent_name = agent_config["name"]

        try:
            # Load and execute agent
            agent = agent_factory.create_agent(agent_config)
            result = agent.execute(state["stage_input"])

            return {
                "agent_outputs": {agent_name: result["output"]},
                "agent_statuses": {agent_name: "success"}
            }
        except Exception as e:
            return {
                "agent_statuses": {agent_name: "failed"},
                "errors": {agent_name: str(e)}
            }

    return agent_node
```

#### Synthesis Node

```python
def _run_synthesis(state: ParallelStageState) -> Dict[str, Any]:
    """Synthesize outputs from parallel agents."""

    # Get successful agent outputs
    agent_outputs = state.get("agent_outputs", {})
    statuses = state.get("agent_statuses", {})

    successful_outputs = [
        AgentOutput(name, output, ...)
        for name, output in agent_outputs.items()
        if statuses.get(name) == "success"
    ]

    # Check minimum successful agents
    min_required = stage_config.get("error_handling", {}).get("min_successful_agents", 1)
    if len(successful_outputs) < min_required:
        raise RuntimeError(f"Only {len(successful_outputs)}/{len(agents)} agents succeeded")

    # Get strategy from registry
    strategy_name = stage_config.get("collaboration", {}).get("strategy", "consensus")
    strategy = strategy_registry.get(strategy_name)

    # Synthesize
    synthesis_result = strategy.synthesize(
        successful_outputs,
        stage_config.get("collaboration", {}).get("config", {})
    )

    return {
        "decision": synthesis_result.decision,
        "confidence": synthesis_result.confidence,
        "synthesis_metadata": {
            "method": synthesis_result.method,
            "votes": synthesis_result.votes,
            "conflicts": synthesis_result.conflicts
        }
    }
```

### Collaboration Strategies

#### Strategy Interface

```python
from typing import List, Dict, Any
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class AgentOutput:
    agent_name: str
    decision: Any
    reasoning: str
    confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class SynthesisResult:
    decision: Any
    confidence: float
    method: str
    votes: Dict[str, int]
    conflicts: List[Conflict]
    reasoning: str
    metadata: Dict[str, Any] = field(default_factory=dict)

class CollaborationStrategy(ABC):
    """Base class for all collaboration strategies."""

    @abstractmethod
    def synthesize(
        self,
        agent_outputs: List[AgentOutput],
        config: Dict[str, Any]
    ) -> SynthesisResult:
        """Synthesize agent outputs into unified decision."""
        pass

    @abstractmethod
    def get_capabilities(self) -> Dict[str, bool]:
        """Return strategy capabilities."""
        pass
```

#### Consensus Strategy

Democratic majority voting with confidence tracking:

```python
class ConsensusStrategy(CollaborationStrategy):
    """Simple majority voting."""

    def synthesize(
        self,
        agent_outputs: List[AgentOutput],
        config: Dict[str, Any]
    ) -> SynthesisResult:
        # Count votes
        votes = {}
        for output in agent_outputs:
            decision = str(output.decision)
            votes[decision] = votes.get(decision, 0) + 1

        # Find majority
        majority_decision = max(votes, key=votes.get)
        majority_size = votes[majority_decision]

        # Calculate confidence
        consensus_strength = majority_size / len(agent_outputs)
        avg_confidence = np.mean([
            o.confidence for o in agent_outputs
            if str(o.decision) == majority_decision
        ])
        confidence = consensus_strength * avg_confidence

        # Detect conflicts
        threshold = config.get("conflict_threshold", 0.3)
        disagreement = 1.0 - consensus_strength
        conflicts = []
        if disagreement > threshold:
            conflicts = self.detect_conflicts(agent_outputs, threshold)

        return SynthesisResult(
            decision=majority_decision,
            confidence=confidence,
            method="consensus",
            votes=votes,
            conflicts=conflicts,
            reasoning=f"Majority vote: {majority_size}/{len(agent_outputs)} agents"
        )

    def get_capabilities(self) -> Dict[str, bool]:
        return {
            "supports_debate": False,
            "supports_convergence": False,
            "deterministic": True
        }
```

**Configuration:**
```yaml
collaboration:
  strategy: consensus
  config:
    threshold: 0.5
    require_unanimous: false
    conflict_threshold: 0.3
```

**Performance:** <10ms latency, O(n) complexity

#### Debate Strategy

Multi-round structured debate with convergence detection:

```python
class DebateAndSynthesize(CollaborationStrategy):
    """Multi-round debate with convergence."""

    def synthesize(
        self,
        agent_outputs: List[AgentOutput],
        config: Dict[str, Any]
    ) -> SynthesisResult:
        max_rounds = config.get("max_rounds", 3)
        convergence_threshold = config.get("convergence_threshold", 0.8)

        # Initialize debate history
        debate_history = []
        previous_positions = {}

        # Round 1: Initial positions
        current_outputs = agent_outputs
        debate_history.append({
            "round_number": 0,
            "outputs": current_outputs,
            "convergence_score": 0.0
        })

        # Iterative debate rounds
        for round_num in range(1, max_rounds):
            # Share arguments with all agents
            context = self._build_debate_context(debate_history)

            # Agents refine positions
            new_outputs = []
            unchanged_count = 0

            for agent_output in current_outputs:
                # Agent sees others' arguments and refines
                new_output = self._agent_refine_position(
                    agent_output, context
                )
                new_outputs.append(new_output)

                # Track if position changed
                prev_decision = previous_positions.get(agent_output.agent_name)
                if prev_decision == str(new_output.decision):
                    unchanged_count += 1

                previous_positions[agent_output.agent_name] = str(new_output.decision)

            # Calculate convergence
            convergence_score = unchanged_count / len(agent_outputs)

            debate_history.append({
                "round_number": round_num,
                "outputs": new_outputs,
                "convergence_score": convergence_score
            })

            # Check convergence
            if convergence_score >= convergence_threshold:
                break

            current_outputs = new_outputs

        # Extract final consensus
        final_outputs = debate_history[-1]["outputs"]
        votes = calculate_vote_distribution(final_outputs)
        majority_decision = max(votes, key=votes.get)

        # Calculate confidence (bonus for convergence)
        converged = debate_history[-1]["convergence_score"] >= convergence_threshold
        base_confidence = votes[majority_decision] / len(final_outputs)
        confidence = base_confidence * (1.2 if converged else 1.0)
        confidence = min(confidence, 1.0)

        return SynthesisResult(
            decision=majority_decision,
            confidence=confidence,
            method="debate_and_synthesize",
            votes=votes,
            conflicts=[],
            reasoning=f"Debate converged after {len(debate_history)-1} rounds",
            metadata={
                "debate_history": debate_history,
                "total_rounds": len(debate_history) - 1,
                "converged": converged,
                "convergence_round": len(debate_history) - 1 if converged else None
            }
        )

    def get_capabilities(self) -> Dict[str, bool]:
        return {
            "supports_debate": True,
            "supports_convergence": True,
            "deterministic": False
        }
```

**Configuration:**
```yaml
collaboration:
  strategy: debate_and_synthesize
  config:
    max_rounds: 3
    convergence_threshold: 0.8
    min_rounds: 1
    debate_structure: round_robin
```

**Performance:** 3-10x single-round latency (depends on LLM API)

#### Merit-Weighted Resolver

Conflict resolver that weights votes by agent merit:

```python
class MeritWeightedResolver:
    """Resolve conflicts using agent merit scores."""

    def resolve(
        self,
        conflict: Conflict,
        context: ResolutionContext
    ) -> Resolution:
        # Calculate composite merit for each agent
        merit_weights = {
            "domain_merit": 0.4,
            "overall_merit": 0.3,
            "recent_performance": 0.3
        }

        weighted_votes = {}
        for agent_name in conflict.agents:
            agent_merit = context.agent_merits[agent_name]
            agent_output = context.agent_outputs[agent_name]

            # Composite merit
            composite_merit = (
                agent_merit.domain_merit * merit_weights["domain_merit"] +
                agent_merit.overall_merit * merit_weights["overall_merit"] +
                agent_merit.recent_performance * merit_weights["recent_performance"]
            )

            # Weight vote: merit × confidence
            vote_weight = composite_merit * agent_output.confidence

            decision = str(agent_output.decision)
            weighted_votes[decision] = weighted_votes.get(decision, 0) + vote_weight

        # Select highest weighted
        resolution_decision = max(weighted_votes, key=weighted_votes.get)
        resolution_confidence = weighted_votes[resolution_decision]

        # Check thresholds
        auto_resolve_threshold = 0.85
        escalation_threshold = 0.5

        if resolution_confidence >= auto_resolve_threshold:
            status = "auto_resolved"
        elif resolution_confidence < escalation_threshold:
            status = "escalate_to_human"
        else:
            status = "resolved_with_low_confidence"

        return Resolution(
            decision=resolution_decision,
            confidence=resolution_confidence,
            method="merit_weighted",
            status=status,
            reasoning=f"Weighted votes: {weighted_votes}"
        )
```

**Configuration:**
```yaml
collaboration:
  strategy: consensus
  conflict_resolver: merit_weighted
  config:
    merit_weights:
      domain_merit: 0.4
      overall_merit: 0.3
      recent_performance: 0.3
    auto_resolve_threshold: 0.85
    escalation_threshold: 0.5
```

**Performance:** <20ms latency (includes DB query for merit scores)

### Convergence Detection

Automatic detection when agents reach agreement:

```python
def calculate_convergence(
    previous_outputs: List[AgentOutput],
    current_outputs: List[AgentOutput]
) -> float:
    """Calculate convergence score between rounds."""

    unchanged_count = 0
    for prev, curr in zip(previous_outputs, current_outputs):
        if prev.agent_name == curr.agent_name:
            if str(prev.decision) == str(curr.decision):
                unchanged_count += 1

    convergence_score = unchanged_count / len(previous_outputs)
    return convergence_score
```

**Early Termination:**
```python
if convergence_score >= convergence_threshold:
    # Agents have reached stable agreement
    break  # Stop debate early
```

**Benefits:**
- Cost savings (fewer LLM calls)
- Higher confidence (stable consensus)
- Faster execution

**Configuration:**
```yaml
convergence:
  enabled: true
  threshold: 0.8  # 80% unchanged
  early_termination: true
  track_position_changes: true
```

### Quality Gates

Validate synthesis output before proceeding:

```python
class QualityGateValidator:
    """Validate synthesis results against quality criteria."""

    def validate(
        self,
        synthesis_result: SynthesisResult,
        quality_config: Dict[str, Any]
    ) -> ValidationResult:
        """Check if synthesis meets quality gates."""

        violations = []

        # Check minimum confidence
        min_confidence = quality_config.get("min_confidence", 0.7)
        if synthesis_result.confidence < min_confidence:
            violations.append(f"Confidence {synthesis_result.confidence:.2f} < {min_confidence}")

        # Check minimum findings
        min_findings = quality_config.get("min_findings")
        if min_findings:
            findings_count = len(synthesis_result.metadata.get("findings", []))
            if findings_count < min_findings:
                violations.append(f"Only {findings_count}/{min_findings} findings")

        # Check citations required
        if quality_config.get("require_citations", False):
            if not synthesis_result.metadata.get("citations"):
                violations.append("No citations provided")

        # Determine action
        if violations:
            on_failure = quality_config.get("on_failure", "retry_stage")
            return ValidationResult(
                passed=False,
                violations=violations,
                action=on_failure
            )

        return ValidationResult(passed=True, violations=[], action="proceed")
```

**Configuration:**
```yaml
quality_gates:
  enabled: true
  min_confidence: 0.7
  min_findings: 5
  require_citations: true
  on_failure: retry_stage  # or escalate, proceed_with_warning
  max_retries: 2
```

**Status:** Pending full implementation (m3-12)

### Performance Metrics

**Execution Speed:**

| Scenario | Sequential | Parallel | Speedup |
|----------|-----------|----------|---------|
| 3 agents (15s each) | 45s | 20s | 2.25x |
| 5 agents (15s each) | 75s | 25s | 3.0x |
| 3 agents + debate (3 rounds) | 135s | 60s | 2.25x |

**Strategy Performance:**

| Strategy | Latency | Quality | Use Case |
|----------|---------|---------|----------|
| Consensus | <10ms | Good | Quick decisions |
| Debate (2 rounds) | 2-6s/round | High | Critical decisions |
| Merit-Weighted | <20ms | Expert-driven | Varying expertise |

**Test Coverage:** 31/34 tests passing (91%)

### Configuration Example

Complete stage configuration with M3 features:

```yaml
stage:
  name: parallel_research
  type: multi_agent_parallel

  agents:
    - name: market_researcher
      config_path: configs/agents/market_researcher.yaml
      role: market_analysis
    - name: competitor_researcher
      config_path: configs/agents/competitor_researcher.yaml
      role: competitive_analysis
    - name: user_researcher
      config_path: configs/agents/user_researcher.yaml
      role: user_research

  execution:
    agent_mode: parallel
    max_concurrent: 3
    timeout_seconds: 600

  error_handling:
    min_successful_agents: 2
    on_agent_failure: continue_with_remaining

  collaboration:
    strategy: consensus
    conflict_resolver: merit_weighted
    config:
      threshold: 0.5
      conflict_threshold: 0.3

  convergence:
    enabled: true
    threshold: 0.8
    early_termination: true

  quality_gates:
    enabled: true
    min_confidence: 0.7
    min_findings: 5
    on_failure: retry_stage
    max_retries: 2
```

### Documentation References

- **User Guide:** [Multi-Agent Collaboration](./docs/features/collaboration/multi_agent_collaboration.md)
- **Strategy Reference:** [Collaboration Strategies](./docs/features/collaboration/collaboration_strategies.md)
- **Examples:** [M3 Examples](./examples/guides/multi_agent_collaboration_examples.md)
- **Completion Report:** [M3 Status](./docs/milestones/milestone3_completion.md)

---

## Safety System

### Multi-Layer Safety Composition

```python
class SafetyEnforcer:
    """
    Enforces safety policies across multiple configuration layers.

    Composition strategies:
    - MostRestrictive: Safest setting wins
    - MostSpecific: Tool > Agent > Stage > Workflow
    - CustomRuleBased: User-defined logic
    - RiskScoreBased: Calculate risk, apply threshold
    """

    def __init__(self, composition_strategy: str):
        self.strategy = self._get_strategy(composition_strategy)

    def check_action(
        self,
        action: Action,
        tool_config: ToolConfig,
        agent_config: AgentConfig,
        stage_config: StageConfig,
        workflow_config: WorkflowConfig
    ) -> SafetyDecision:
        """
        Check if action is allowed based on composed safety rules.

        Returns:
            SafetyDecision with:
            - allowed: bool
            - mode: execute | dry_run | require_approval
            - reason: str
            - risk_score: float
            - applied_rules: List[str]
        """
        decision = self.strategy.compose(
            action=action,
            tool_safety=tool_config.safety,
            agent_safety=agent_config.safety,
            stage_safety=stage_config.safety,
            workflow_safety=workflow_config.safety
        )

        return decision

class SafetyDecision:
    """Result of safety check"""
    allowed: bool
    mode: SafetyMode  # execute | dry_run | require_approval
    reason: str
    risk_score: float
    applied_rules: List[str]
    requires_human_approval: bool
    approval_context: Dict[str, Any]

class MostRestrictiveStrategy:
    """Most restrictive safety rule wins"""

    def compose(self, action, tool_safety, agent_safety, stage_safety, workflow_safety):
        # Collect all safety settings
        settings = [tool_safety, agent_safety, stage_safety, workflow_safety]

        # Most restrictive mode
        mode_priority = [SafetyMode.REQUIRE_APPROVAL, SafetyMode.DRY_RUN, SafetyMode.EXECUTE]
        for mode in mode_priority:
            if any(s.mode == mode for s in settings):
                return SafetyDecision(
                    allowed=True,
                    mode=mode,
                    reason="Most restrictive safety mode applied",
                    risk_score=max(s.risk_level for s in settings),
                    applied_rules=["MostRestrictive"]
                )

        return SafetyDecision(allowed=True, mode=SafetyMode.EXECUTE)

class RiskScoredStrategy:
    """Calculate risk score, apply threshold"""

    def compose(self, action, tool_safety, agent_safety, stage_safety, workflow_safety):
        # Calculate risk score
        risk_score = self._calculate_risk(
            action,
            [tool_safety, agent_safety, stage_safety, workflow_safety]
        )

        # Apply thresholds
        if risk_score > 0.8:
            mode = SafetyMode.REQUIRE_APPROVAL
        elif risk_score > 0.5:
            mode = SafetyMode.DRY_RUN
        else:
            mode = SafetyMode.EXECUTE

        return SafetyDecision(
            allowed=True,
            mode=mode,
            reason=f"Risk score: {risk_score:.2f}",
            risk_score=risk_score,
            applied_rules=["RiskScored"]
        )

    def _calculate_risk(self, action, safety_configs):
        """Calculate overall risk score 0-1"""
        factors = {
            "action_type": self._action_type_risk(action),
            "tool_risk": max((s.risk_level for s in safety_configs), default=0),
            "blast_radius": self._blast_radius_risk(action),
            "reversibility": self._reversibility_risk(action),
        }

        # Weighted average
        weights = {"action_type": 0.3, "tool_risk": 0.3, "blast_radius": 0.2, "reversibility": 0.2}
        risk = sum(factors[k] * weights[k] for k in factors)

        return risk
```

---

## Complete Examples

### Example 1: Simple Research Agent

**File:** `configs/agents/simple_researcher.yaml`

```yaml
agent:
  name: simple_researcher
  description: "Basic research agent for testing"

  prompt:
    inline: "You are a researcher. Analyze the given topic and provide insights."

  inference:
    provider: ollama
    model: llama3.2:3b
    base_url: http://localhost:11434
    temperature: 0.7

  tools:
    - WebScraper
    - Calculator

  safety:
    mode: execute
    max_tool_calls_per_execution: 5

  memory:
    enabled: false

  error_handling:
    retry_strategy: ExponentialBackoff
    max_retries: 2
```

### Example 2: Multi-Agent Research Stage

**File:** `configs/stages/research_stage.yaml`

```yaml
stage:
  name: research
  agents:
    - market_researcher
    - competitor_analyst
    - user_researcher

  collaboration:
    strategy: DebateAndSynthesize
    max_rounds: 2

  conflict_resolution:
    strategy: MeritWeighted

  safety:
    mode: execute
```

### Example 3: Complete MVP Workflow

**File:** `configs/workflows/mvp_lifecycle.yaml`

```yaml
workflow:
  name: mvp_lifecycle
  product_type: web_app

  stages:
    - name: research
      stage_ref: research_stage

    - name: requirements
      stage_ref: requirements_stage
      depends_on: [research]

    - name: build
      stage_ref: build_stage
      depends_on: [requirements]

  safety:
    composition_strategy: MostRestrictive
    approval_required_stages: [build]

  observability:
    console_mode: standard
```

### Example 4: Feedback Trigger

**File:** `configs/triggers/feedback_processor.yaml`

```yaml
trigger:
  name: feedback_processor
  type: EventTrigger

  source:
    type: message_queue
    queue_name: user_feedback

  filter:
    event_type: new_feedback

  workflow: feedback_to_improvement

  workflow_inputs:
    feedback_text: ${event.body.text}
```

---

## Implementation Notes

### Technology Requirements

**Core:**
- Python 3.11+
- LangChain
- LangGraph
- PyYAML
- Pydantic
- SQLModel

**Inference:**
- httpx (for API calls)
- ollama-python (optional)
- openai-python (optional)
- anthropic-python (optional)

**Observability:**
- SQLAlchemy
- Rich (console UI)
- Prometheus client (optional)

**Tools:**
- beautifulsoup4 (web scraping)
- requests
- Additional tool-specific dependencies

### Directory Structure

```
meta-autonomous-framework/
├── configs/                 # All YAML configs
│   ├── agents/
│   ├── stages/
│   ├── workflows/
│   ├── tools/
│   ├── prompts/
│   └── triggers/
├── src/
│   ├── compiler/           # YAML → LangGraph compiler
│   ├── agents/             # Agent implementations
│   ├── tools/              # Tool implementations
│   ├── strategies/         # Collaboration/conflict modules
│   ├── safety/             # Safety enforcement
│   ├── observability/      # Tracing, logging, metrics
│   └── cli/                # Command-line interface
├── tests/
├── docs/
└── examples/
```

---

## Related Documents

- [Vision Document](./docs/VISION.md) - Why this exists and where it's going
- [Roadmap](./ROADMAP.md) - Implementation phases (if needed)

---

**Last Updated:** 2026-01-26
**Status:** Technical Specification - Implementation Guide (M3: 69% Complete)
**Next:** Complete M3 quality gates and E2E tests, then proceed to M4 (Safety & Experimentation)
