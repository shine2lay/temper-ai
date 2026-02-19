# M5 Modular Architecture Design

**Status:** 🚧 In Progress - Active Discussion
**Last Updated:** 2026-02-01
**Purpose:** Living document capturing architectural decisions for M5's plugin-based design

---

## Vision

M5 Self-Improvement Loop must be **modular and extensible** from day one. Different agents have different needs, and the system should grow with the project without requiring core rewrites.

**Core Principle:** Build interfaces and registries, ship built-in implementations, enable user extensions.

---

## Modularity Points

| Component | Priority | Status | Discussed |
|-----------|----------|--------|-----------|
| 1. Metric Collectors | 🔴 Critical | ✅ Decided | Yes |
| 2. Improvement Strategies | 🔴 Critical | ✅ Decided | Yes |
| 3. Hybrid Trigger System | 🔴 Critical | ✅ Decided | Yes |
| 4. Pattern Extractors | 🟡 TBD | 🚧 Pending | No |
| 5. Experiment Types | 🟡 TBD | 🚧 Pending | No |
| 6. Rollout Strategies | 🟡 TBD | 🚧 Pending | No |

---

## 1. Metric Collectors (What to Measure)

### Decision: ✅ CRITICAL - Must Have from Day 1

### Problem
Different agents need different performance metrics:
- Code generation agents: `test_pass_rate`, `code_quality`, `compilation_success`
- Research agents: `factual_accuracy`, `completeness`, `citation_quality`
- Customer support agents: `customer_satisfaction`, `resolution_rate`
- Creative writing agents: `readability`, `engagement_score`, `tone_match`

Without modularity, M5 is locked to whatever metrics ship with it.

### Solution: Plugin Architecture

#### Interface
```python
class MetricCollector(ABC):
    """Base class for all metric collectors."""

    @property
    @abstractmethod
    def metric_name(self) -> str:
        """Unique metric identifier (e.g., 'quality_score')."""
        pass

    @property
    @abstractmethod
    def metric_type(self) -> str:
        """Type: 'automatic', 'derived', 'custom'."""
        pass

    @abstractmethod
    def collect(self, execution: AgentExecution) -> Optional[float]:
        """
        Extract metric value from execution.
        Returns float (0-1) if available, None otherwise.
        """
        pass

    @abstractmethod
    def is_applicable(self, execution: AgentExecution) -> bool:
        """Check if this metric applies to this execution."""
        pass
```

#### Registry
```python
class MetricRegistry:
    """Central registry for all metric collectors."""

    def __init__(self):
        self._collectors = {}

    def register(self, collector: MetricCollector):
        """Add a new metric collector."""
        self._collectors[collector.metric_name] = collector

    def collect_all(self, execution: AgentExecution) -> Dict[str, float]:
        """Collect all applicable metrics for an execution."""
        metrics = {}
        for name, collector in self._collectors.items():
            if collector.is_applicable(execution):
                value = collector.collect(execution)
                if value is not None:
                    metrics[name] = value
        return metrics
```

#### Built-in Collectors (Ship with M5)
```python
# Always available
- SuccessRateCollector()   # status = 'completed'
- CostCollector()           # total_cost_usd
- DurationCollector()       # duration_seconds
- TokenUsageCollector()     # total_tokens

# Derived from logs (when applicable)
- TestQualityCollector()    # Parse test results from tool calls
- ErrorRateCollector()      # Count failures
- RetryCountCollector()     # Average retries
```

#### User Extensions (Examples)
```python
# Users add domain-specific collectors
class CodeQualityCollector(MetricCollector):
    """Static analysis quality score."""
    metric_name = "code_quality_score"

    def collect(self, execution):
        code = execution.output
        pylint_score = run_pylint(code) / 10
        complexity = calculate_complexity(code) / 100
        return pylint_score * 0.6 + (1 - complexity) * 0.4

    def is_applicable(self, execution):
        return "code" in execution.input_data.get("task_type", "")

class FactualAccuracyCollector(MetricCollector):
    """LLM-as-judge fact checking."""
    metric_name = "factual_accuracy"

    def collect(self, execution):
        return llm_judge.verify_facts(execution.output)

    def is_applicable(self, execution):
        return "research" in execution.input_data.get("task_type", "")
```

#### Critical Design Decision: Compute Once, Query Later

**Key Insight:** MetricCollectors should compute custom metrics **after each execution** and store in database, NOT during analysis.

**Why?**
- Computing metrics is expensive (LLM-as-judge, static analysis, etc.)
- Don't want to recompute same metrics every hour during analysis
- Database aggregation (SQL) is much faster than Python loops

**Architecture:**

```
Execution completes
    ↓
MetricCollectors.collect_all(execution)  ← Compute custom metrics ONCE
    ↓
Store in custom_metrics table
    ↓
[Hours/Days later]
    ↓
PerformanceAnalyzer queries database with SQL  ← Fast aggregation
    ↓
Returns AgentPerformanceProfile
```

### Integration: MetricCollectors → Database → PerformanceAnalyzer

#### Step 1: After Each Execution (Real-time Metric Collection)

```python
# temper_ai/observability/execution_tracker.py

class ExecutionTracker:
    def __init__(self, metric_registry: MetricRegistry):
        self.metric_registry = metric_registry

    def complete_agent_execution(self, execution: AgentExecution):
        """Called when agent execution completes."""

        # M1: Store basic execution data
        self.db.save(execution)
        # Stores: status, duration_seconds, total_cost_usd, total_tokens, etc.

        # M5: Compute custom metrics using collectors
        custom_metrics = self.metric_registry.collect_all(execution)
        # Result: {
        #   "success_rate": 1.0,           # From SuccessRateCollector
        #   "cost_usd": 0.78,              # From CostCollector
        #   "duration_seconds": 42.5,      # From DurationCollector
        #   "quality_score": 0.85,         # From custom QualityCollector
        #   "code_complexity": 12.5        # From custom ComplexityCollector
        # }

        # Store ONLY custom metrics (built-ins already in agent_executions table)
        for metric_name, value in custom_metrics.items():
            if metric_name not in BUILTIN_METRICS:
                self.db.execute(
                    "INSERT INTO custom_metrics "
                    "(workflow_execution_id, metric_name, metric_value, recorded_at) "
                    "VALUES (:exec_id, :name, :value, :timestamp)",
                    {
                        "exec_id": execution.id,
                        "name": metric_name,
                        "value": value,
                        "timestamp": utcnow()
                    }
                )
```

#### Step 2: During Analysis (Query Database)

```python
# temper_ai/self_improvement/performance_analyzer.py

class PerformanceAnalyzer:
    def __init__(self, db):
        self.db = db
        # NO metric_registry needed here! Just query DB.

    def analyze_agent_performance(
        self,
        agent_name: str,
        window_hours: int = 168
    ) -> AgentPerformanceProfile:
        """Query database for all metrics (fast SQL aggregation)."""

        cutoff = utcnow() - timedelta(hours=window_hours)

        # Query 1: Built-in metrics from agent_executions
        builtin_query = """
        SELECT
            COUNT(*) as total_executions,
            AVG(CASE WHEN status = 'completed' THEN 1.0 ELSE 0.0 END) as success_rate,
            AVG(total_cost_usd) as avg_cost_usd,
            STDDEV(total_cost_usd) as std_cost_usd,
            AVG(duration_seconds) as avg_duration_seconds,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_seconds) as p95_duration
        FROM agent_executions
        WHERE agent_name = :agent_name AND created_at >= :cutoff
        """

        builtin = self.db.execute(builtin_query, {"agent_name": agent_name, "cutoff": cutoff}).fetchone()

        # Query 2: Custom metrics from custom_metrics table
        custom_query = """
        SELECT
            cm.metric_name,
            AVG(cm.metric_value) as mean,
            STDDEV(cm.metric_value) as std,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY cm.metric_value) as p95
        FROM custom_metrics cm
        JOIN agent_executions ae ON cm.workflow_execution_id = ae.id
        WHERE ae.agent_name = :agent_name AND ae.created_at >= :cutoff
        GROUP BY cm.metric_name
        """

        custom = self.db.execute(custom_query, {"agent_name": agent_name, "cutoff": cutoff}).fetchall()

        # Combine results
        metrics = {
            "success_rate": {"mean": builtin.success_rate},
            "cost_usd": {"mean": builtin.avg_cost_usd, "std": builtin.std_cost_usd},
            "duration_seconds": {"mean": builtin.avg_duration_seconds, "p95": builtin.p95_duration}
        }

        for row in custom:
            metrics[row.metric_name] = {"mean": row.mean, "std": row.std, "p95": row.p95}

        return AgentPerformanceProfile(
            agent_name=agent_name,
            total_executions=builtin.total_executions,
            metrics=metrics,
            window_start=cutoff,
            window_end=utcnow()
        )
```

### Database Schema for Custom Metrics

```sql
CREATE TABLE custom_metrics (
    id TEXT PRIMARY KEY,
    workflow_execution_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    metric_metadata JSON,
    recorded_at TIMESTAMP NOT NULL,

    FOREIGN KEY (workflow_execution_id) REFERENCES workflow_executions(id),
    INDEX idx_custom_metrics_workflow (workflow_execution_id),
    INDEX idx_custom_metrics_name (metric_name),
    INDEX idx_custom_metrics_lookup (workflow_execution_id, metric_name)
);
```

### When MetricCollectors ARE Used

| When | Purpose | Why |
|------|---------|-----|
| After each execution | Compute custom metrics | Store for later analysis |
| Backfill old data | Retroactive metric computation | Apply new collectors to historical executions |
| One-off analysis | Ad-hoc metric extraction | Debugging, research |

### When MetricCollectors are NOT Used

| When | Use Instead | Why |
|------|-------------|-----|
| During analysis (PerformanceAnalyzer) | SQL queries | Much faster (database aggregation) |
| Trend analysis | SQL window functions | Efficient time-series queries |
| Dashboards | SQL views/materialized views | Real-time performance |

### Benefits
- ✅ Start with basic metrics (success, cost, speed)
- ✅ Add quality metrics later without touching M5 core
- ✅ Different metrics for different agent types
- ✅ Retroactive analysis (run new collectors on old data)

### Timeline
- **Month 1:** Ship with 4 built-in collectors (success, cost, duration, tokens)
- **Month 3:** Add test_quality_collector for code agents
- **Month 6:** Users add custom collectors (factual_accuracy, customer_sat, etc.)
- **Month 12:** Rich ecosystem of domain-specific collectors

---

## 2. Improvement Strategies (How to Optimize)

### Decision: ✅ CRITICAL - Must Have from Day 1

### Problem
When M5 detects a performance issue, it needs to know **what to change** to fix it. Different problems need different solutions:
- Cost too high → Use cheaper model, reduce tokens, enable caching
- Quality too low → Add examples to prompt, adjust temperature
- Too slow → Reduce max_tokens, parallelize, use faster model
- Edge case failures → Improve tool selection, add error handling

Without modularity, M5 can only optimize in one hardcoded way.

### Solution: Strategy Plugin System

#### Interface
```python
class ImprovementStrategy(ABC):
    """Base class for all improvement strategies."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy identifier (e.g., 'prompt_tuning')."""
        pass

    @abstractmethod
    def generate_variants(
        self,
        current_config: AgentConfig,
        patterns: List[LearnedPattern]
    ) -> List[AgentConfig]:
        """
        Generate improved config variants to test.

        Args:
            current_config: Current agent configuration
            patterns: Learned patterns from PatternLearner

        Returns:
            List of variant configs to experiment with
        """
        pass

    @abstractmethod
    def is_applicable(self, problem_type: str) -> bool:
        """Check if this strategy applies to the detected problem."""
        pass

    def estimate_impact(self, problem: ProblemDescription) -> float:
        """Estimate expected improvement (0-1 scale)."""
        return 0.1  # Default conservative estimate
```

#### Registry
```python
class StrategyRegistry:
    """Central registry for improvement strategies."""

    def __init__(self):
        self._strategies = {}

    def register(self, strategy: ImprovementStrategy):
        """Add a new improvement strategy."""
        self._strategies[strategy.name] = strategy

    def get(self, name: str) -> ImprovementStrategy:
        """Get strategy by name."""
        return self._strategies.get(name)

    def find_applicable(self, problem_type: str) -> List[ImprovementStrategy]:
        """Find all strategies that apply to this problem type."""
        return [s for s in self._strategies.values()
                if s.is_applicable(problem_type)]
```

#### Built-in Strategies (Ship with M5)

**1. PromptTuningStrategy**
```python
class PromptTuningStrategy(ImprovementStrategy):
    """Optimizes agent prompts based on learned patterns."""

    name = "prompt_tuning"

    def generate_variants(self, current_config, patterns):
        variants = []

        # Pattern: "Examples improve quality"
        if patterns.find("include_examples_success"):
            variant = current_config.copy()
            variant["prompt"]["include_examples"] = True
            variant["prompt"]["num_examples"] = 3
            variants.append(variant)

        # Pattern: "Structured prompts perform better"
        if patterns.find("structured_prompt_success"):
            variant = current_config.copy()
            variant["prompt"]["template"] = "structured_format.txt"
            variants.append(variant)

        return variants

    def is_applicable(self, problem_type):
        return problem_type in ["quality_low", "accuracy_low", "inconsistent"]
```

**2. CostReductionStrategy**
```python
class CostReductionStrategy(ImprovementStrategy):
    """Reduces costs while maintaining quality."""

    name = "cost_reduction"

    def generate_variants(self, current_config, patterns):
        variants = []

        # Variant 1: Reduce max_tokens
        variant1 = current_config.copy()
        current_tokens = current_config["inference"]["max_tokens"]
        variant1["inference"]["max_tokens"] = int(current_tokens * 0.75)
        variants.append(variant1)

        # Variant 2: Use cheaper model
        if current_config["inference"]["model"] == "gpt-4":
            variant2 = current_config.copy()
            variant2["inference"]["model"] = "gpt-3.5-turbo"
            variant2["prompt"]["include_reasoning_guide"] = True
            variants.append(variant2)

        # Variant 3: Enable caching
        variant3 = current_config.copy()
        variant3["caching"]["enabled"] = True
        variants.append(variant3)

        return variants

    def is_applicable(self, problem_type):
        return problem_type == "cost_too_high"
```

**3. ParameterTuningStrategy**
```python
class ParameterTuningStrategy(ImprovementStrategy):
    """Tunes inference parameters (temperature, top_p, etc.)."""

    name = "parameter_tuning"

    def generate_variants(self, current_config, patterns):
        variants = []
        current_temp = current_config["inference"]["temperature"]

        # Test lower temperature (more deterministic)
        if current_temp > 0.3:
            variant1 = current_config.copy()
            variant1["inference"]["temperature"] = max(0.3, current_temp - 0.2)
            variants.append(variant1)

        # Test higher temperature (more creative)
        if current_temp < 0.9:
            variant2 = current_config.copy()
            variant2["inference"]["temperature"] = min(0.9, current_temp + 0.2)
            variants.append(variant2)

        return variants

    def is_applicable(self, problem_type):
        return problem_type in ["quality_low", "inconsistent", "too_conservative"]
```

**4. SpeedOptimizationStrategy**
```python
class SpeedOptimizationStrategy(ImprovementStrategy):
    """Reduces latency while maintaining quality."""

    name = "speed_optimization"

    def generate_variants(self, current_config, patterns):
        variants = []

        # Reduce max_tokens for speed
        variant1 = current_config.copy()
        variant1["inference"]["max_tokens"] = int(
            current_config["inference"]["max_tokens"] * 0.7
        )
        variants.append(variant1)

        # Use faster model
        model_speeds = {"gpt-4": "gpt-3.5-turbo", "claude-2": "claude-instant"}
        current_model = current_config["inference"]["model"]
        if current_model in model_speeds:
            variant2 = current_config.copy()
            variant2["inference"]["model"] = model_speeds[current_model]
            variants.append(variant2)

        return variants

    def is_applicable(self, problem_type):
        return problem_type in ["too_slow", "latency_high"]
```

#### User Extensions (Examples)

**Domain-Specific Strategy:**
```python
class LegalDocumentStrategy(ImprovementStrategy):
    """Custom optimization for legal document generation."""

    name = "legal_document_optimization"

    def generate_variants(self, current_config, patterns):
        variants = []

        # Legal requires high precision
        variant1 = current_config.copy()
        variant1["inference"]["temperature"] = 0.1
        variant1["prompt"]["include_citations"] = True
        variant1["prompt"]["require_source_verification"] = True
        variants.append(variant1)

        # Legal requires structure
        variant2 = current_config.copy()
        variant2["prompt"]["template"] = "legal_document_template.txt"
        variant2["prompt"]["sections"] = [
            "preamble", "definitions", "clauses", "signatures"
        ]
        variants.append(variant2)

        return variants

    def is_applicable(self, problem_type):
        return problem_type == "legal_accuracy_low"
```

#### Integration with ImprovementDetector (Detailed Flow)

**When:** Daily job (or triggered by user)
**Where:** Strategies get invoked to generate solutions

```python
class ImprovementDetector:
    def __init__(
        self,
        performance_analyzer: PerformanceAnalyzer,
        strategy_registry: StrategyRegistry,
        pattern_learner: PatternLearner
    ):
        self.performance_analyzer = performance_analyzer
        self.strategies = strategy_registry
        self.pattern_learner = pattern_learner

    def detect_improvements(self, agent_name: str) -> List[ImprovementProposal]:
        """Main entry point - detects optimization opportunities."""

        # Step 1: Analyze current vs baseline performance
        current = self.performance_analyzer.analyze_agent_performance(
            agent_name, window_hours=168  # Last 7 days
        )
        baseline = self.performance_analyzer.get_baseline(
            agent_name, window_days=30  # 30-day baseline
        )

        # Step 2: Detect problems
        problems = self._detect_problems(current, baseline)
        # Result: [
        #   {"type": "quality_low", "severity": 0.85,
        #    "current": 0.75, "baseline": 0.85},
        #   {"type": "cost_too_high", "severity": 0.70,
        #    "current": 0.80, "baseline": 0.60}
        # ]

        if not problems:
            return []  # No problems = no improvements needed

        # Step 3: For each problem, ask strategies to generate solutions
        proposals = []
        for problem in problems:
            proposal = self._create_improvement_proposal(agent_name, problem)
            if proposal:
                proposals.append(proposal)

        return proposals

    def _create_improvement_proposal(
        self,
        agent_name: str,
        problem: Dict
    ) -> Optional[ImprovementProposal]:
        """
        THIS IS WHERE STRATEGIES GET INVOKED!
        """

        problem_type = problem["type"]  # e.g., "quality_low"

        # 3a: Find applicable strategies
        applicable_strategies = self.strategies.find_applicable(problem_type)
        # Result: [PromptTuningStrategy(), ParameterTuningStrategy()]

        if not applicable_strategies:
            logger.warning(f"No strategies found for {problem_type}")
            return None

        # 3b: Select best strategy
        selected_strategy = self._select_best_strategy(applicable_strategies, problem)
        # For now: pick first one
        # Future: scoring, multi-strategy, etc.

        # 3c: Get learned patterns (strategies use these)
        patterns = self.pattern_learner.extract_patterns(agent_name)
        # Result: [
        #   Pattern("include_examples_success", support=45, confidence=0.88),
        #   Pattern("structured_prompt_success", support=38, confidence=0.82)
        # ]

        # 3d: Load current config
        current_config = self._load_agent_config(agent_name)

        # 3e: ASK STRATEGY TO GENERATE VARIANTS! ← KEY STEP
        variants = selected_strategy.generate_variants(
            current_config=current_config,
            patterns=patterns
        )
        # Result: [variant_1_config, variant_2_config, variant_3_config]

        if not variants:
            logger.warning(f"Strategy {selected_strategy.name} generated no variants")
            return None

        # 3f: Create improvement proposal
        proposal = ImprovementProposal(
            id=generate_id(),
            agent_name=agent_name,
            problem_type=problem_type,
            problem_severity=problem["severity"],
            strategy_name=selected_strategy.name,
            current_config=current_config,
            variant_configs=variants,
            expected_improvement=selected_strategy.estimate_impact(problem),
            created_at=utcnow()
        )

        return proposal
```

### Complete Integration Flow: Problem Detection → Experiment

```
DAY 1-7: Normal Execution
    Agent executes 150 times
    M1 tracks all executions
    MetricCollectors compute custom metrics after each execution
    ↓
DAY 8: PerformanceAnalyzer runs (scheduled or triggered)
    Queries database for last 7 days
    Computes: current = {quality: 0.75, cost: 0.80}
    Compares to baseline = {quality: 0.85, cost: 0.60}
    Stores AgentPerformanceProfile
    ↓
DAY 9: ImprovementDetector runs (daily job)
    Loads current and baseline profiles
    Detects problems: ["quality_low", "cost_too_high"]
    ↓
    For "quality_low":
        ↓
    StrategyRegistry.find_applicable("quality_low")
        Returns: [PromptTuningStrategy, ParameterTuningStrategy]
        ↓
    Select: PromptTuningStrategy
        ↓
    PatternLearner.extract_patterns("code_review_agent")
        Returns: [Pattern("include_examples_success", conf=0.88)]
        ↓
    PromptTuningStrategy.generate_variants(current_config, patterns)
        Returns: [
            config_with_examples,
            config_structured,
            config_lower_temp
        ]
        ↓
    Create ImprovementProposal
        ↓
DAY 10: ExperimentOrchestrator creates A/B test
    Uses proposal.variant_configs to create experiment
    Starts experiment with control + 3 variants
    ↓
DAY 10-17: Experiment runs
    (Details in Experiment Types section)
    ↓
DAY 17: Winner deployed
    (Details in Rollout Strategies section)
```

### Strategy Selection Logic

```python
def _select_best_strategy(
    self,
    applicable: List[ImprovementStrategy],
    problem: Dict
) -> ImprovementStrategy:
    """Select which strategy to use."""

    if len(applicable) == 1:
        return applicable[0]

    # Score each strategy
    scores = []
    for strategy in applicable:
        score = strategy.estimate_impact(problem)
        scores.append((strategy, score))

    # Sort by estimated impact (highest first)
    scores.sort(key=lambda x: x[1], reverse=True)

    # Return highest-scoring strategy
    return scores[0][0]

    # Future: Could run multiple strategies in parallel
    # Future: Could combine strategies (ensemble)
```

### Benefits
- ✅ Different problems get different solutions
- ✅ Domain-specific optimizations (legal, medical, code, etc.)
- ✅ Strategies can learn from patterns
- ✅ Easy to add new optimization approaches

### Timeline
- **Month 1:** Ship with 4 built-in strategies (prompt, cost, params, speed)
- **Month 3:** Add tool_selection_strategy
- **Month 6:** Users add domain-specific strategies
- **Month 12:** Advanced strategies (multi-objective, RL-based, etc.)

---

## 2.5. PerformanceAnalyzer Deep Dive

### What It Does
PerformanceAnalyzer is the **"WATCH"** component - the first step in M5's loop. It monitors agents and creates performance report cards.

**Job:**
1. Query M1 observability database
2. Aggregate metrics (using SQL, not Python loops!)
3. Create AgentPerformanceProfile
4. Store profiles for trend analysis

### Execution Model: Discrete (Scheduled), Not Continuous

**Why discrete/batch processing?**

✅ **Do this:**
```python
# Scheduled job every hour
00:00 → Analyze all agents (batch query)
01:00 → Analyze all agents
02:00 → Analyze all agents
```

❌ **Don't do this:**
```python
# After every single execution (too expensive!)
Agent execution completes → Analyze performance immediately
```

**Reasons:**

| Reason | Explanation |
|--------|-------------|
| **Database performance** | Batch queries are more efficient than N individual queries |
| **Statistical validity** | Need 50-100 samples for meaningful statistics, not 1-2 |
| **Resource efficiency** | Hourly detection is fast enough, saves compute |
| **Prevents thrashing** | Don't want to trigger improvements on noise |

### Schedule Options

```python
# Recommended schedules by agent traffic
HIGH_TRAFFIC = "0 * * * *"        # Hourly
MEDIUM_TRAFFIC = "0 */4 * * *"    # Every 4 hours
LOW_TRAFFIC = "0 0 * * *"         # Daily
EXPERIMENTAL = "0 0 * * 0"        # Weekly
```

**With Hybrid Triggers (recommended):**
- High-traffic: Analyze when 200 executions OR 1 hour (whichever first)
- Low-traffic: Analyze when 100 executions OR 1 week (whichever first)

### Complete PerformanceAnalyzer Flow

```python
# Triggered by: Schedule OR Hybrid Trigger

def analyze_all_agents():
    """Main entry point called by scheduler or trigger."""

    # Get all unique agent names
    agent_names = db.execute(
        "SELECT DISTINCT agent_name FROM agent_executions"
    ).fetchall()

    for agent_name in agent_names:
        try:
            profile = analyze_agent_performance(agent_name)
            store_profile(profile)
        except Exception as e:
            logger.error(f"Failed to analyze {agent_name}: {e}")

def analyze_agent_performance(agent_name, window_hours=168):
    """Analyze single agent."""

    cutoff = utcnow() - timedelta(hours=window_hours)

    # Query built-in metrics (single SQL query - FAST!)
    builtin_metrics = db.execute("""
        SELECT
            COUNT(*) as total_executions,
            AVG(CASE WHEN status = 'completed' THEN 1.0 ELSE 0.0 END) as success_rate,
            AVG(total_cost_usd) as avg_cost,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_seconds) as p95_latency
        FROM agent_executions
        WHERE agent_name = :name AND created_at >= :cutoff
    """, {"name": agent_name, "cutoff": cutoff}).fetchone()

    # Query custom metrics (single SQL query - FAST!)
    custom_metrics = db.execute("""
        SELECT
            cm.metric_name,
            AVG(cm.metric_value) as mean,
            STDDEV(cm.metric_value) as std
        FROM custom_metrics cm
        JOIN agent_executions ae ON cm.workflow_execution_id = ae.id
        WHERE ae.agent_name = :name AND ae.created_at >= :cutoff
        GROUP BY cm.metric_name
    """, {"name": agent_name, "cutoff": cutoff}).fetchall()

    # Combine and return
    return AgentPerformanceProfile(
        agent_name=agent_name,
        total_executions=builtin_metrics.total_executions,
        metrics={
            "success_rate": {"mean": builtin_metrics.success_rate},
            "cost_usd": {"mean": builtin_metrics.avg_cost},
            "duration_seconds": {"p95": builtin_metrics.p95_latency},
            **{row.metric_name: {"mean": row.mean, "std": row.std}
               for row in custom_metrics}
        }
    )
```

### Performance Profile Output Example

```python
AgentPerformanceProfile(
    id="profile-abc123",
    agent_name="code_review_agent",
    window_start="2026-01-25 00:00:00",
    window_end="2026-02-01 00:00:00",
    total_executions=150,
    metrics={
        # Built-in metrics (from agent_executions table)
        "success_rate": {"mean": 0.92, "std": 0.05},
        "cost_usd": {"mean": 0.80, "std": 0.12},
        "duration_seconds": {"mean": 42.5, "p95": 55.0, "std": 8.5},

        # Custom metrics (from custom_metrics table)
        "quality_score": {"mean": 0.75, "std": 0.08},
        "code_complexity": {"mean": 12.5, "std": 3.2},
        "test_coverage": {"mean": 0.88, "std": 0.05}
    },
    created_at="2026-02-01 10:00:00"
)
```

### Who Uses PerformanceAnalyzer Output?

| Consumer | Uses For | When |
|----------|----------|------|
| **ImprovementDetector** | Compare current vs baseline to detect problems | Daily |
| **Dashboard/UI** | Display agent performance trends | Real-time |
| **Alerting** | Trigger alerts on degradation | Real-time |
| **Reports** | Generate weekly/monthly reports | Scheduled |

### Key Design Principles

1. **Query database, don't compute** - SQL aggregation is 100x faster than Python loops
2. **Batch processing** - Analyze all agents at once, not one at a time
3. **Metric-agnostic** - Doesn't care what metrics exist, just queries whatever's in DB
4. **Stateless** - Each run is independent, stores results for later use

---

## 3. Hybrid Trigger System (When to Analyze)

### Decision: ✅ CRITICAL - Must Have from Day 1

### Problem
Pure time-based scheduling is too rigid and inefficient:

**High-traffic agents:** Waste time waiting for scheduled analysis
- Hour 1: 500 executions (already enough data!)
- Hour 24: 12,000 executions (finally analyze - wasted 23 hours)

**Low-traffic agents:** Analyze with insufficient data
- Day 1: Only 10 executions (not statistically valid)
- Day 7: Only 70 executions (still not enough)

**Parallel execution:** Fixed schedules miss opportunities
- Normal: 10 exec/hour
- Burst: 1000 exec in 5 minutes (should analyze immediately!)

### Solution: Event-Driven Hybrid Triggers

#### Three Trigger Strategies

```python
class TriggerType(Enum):
    TIME_BASED = "time"       # Every N hours (fixed schedule)
    CYCLE_BASED = "cycle"     # After N executions (data-driven)
    HYBRID = "hybrid"         # Whichever comes first (recommended)
```

#### Configuration

```python
@dataclass
class AnalysisTriggerConfig:
    """Configure when performance analysis runs."""

    # Cycle-based (execution count)
    min_executions: int = 100        # Need at least 100 executions
    target_executions: int = 200     # Prefer 200 for better stats

    # Time-based (intervals)
    min_interval_hours: int = 1      # Rate limit: max once/hour
    max_interval_hours: int = 168    # Force analysis after 7 days

    # Hybrid strategy
    trigger_strategy: TriggerType = TriggerType.HYBRID

    # Burst detection
    enable_burst_detection: bool = True
    burst_threshold: int = 500       # 500+ exec in 10min = burst
```

#### Trigger Manager

```python
class AnalysisTriggerManager:
    """Manages when performance analysis should run."""

    def on_execution_complete(self, agent_name: str):
        """
        Called after EVERY agent execution.
        Decides if analysis should trigger.
        """
        self.execution_count_since_last_analysis[agent_name] += 1

        should_trigger, reason = self.should_trigger_analysis(agent_name)

        if should_trigger:
            self._trigger_analysis(agent_name, reason)
            self._reset_counters(agent_name)

    def should_trigger_analysis(self, agent_name: str) -> Tuple[bool, str]:
        """Decide based on multiple criteria."""

        # CHECK 1: Min interval (rate limiting)
        if hours_since_last < min_interval_hours:
            return False, "too_soon"

        # CHECK 2: Max interval (force analysis)
        if hours_since_last >= max_interval_hours:
            return True, "max_interval_exceeded"

        # CHECK 3: Target executions reached
        if exec_count >= target_executions:
            return True, "target_executions_reached"

        # CHECK 4: Burst detected
        if burst_detected and exec_count >= min_executions:
            return True, "burst_detected"

        # CHECK 5: Sufficient new data (dynamic threshold)
        threshold = self._calculate_dynamic_threshold(exec_count, hours_since_last)
        if exec_count >= threshold:
            return True, "sufficient_new_data"

        return False, "waiting_for_more_data"
```

#### Integration Point

```python
# temper_ai/observability/execution_tracker.py

class ExecutionTracker:
    def __init__(
        self,
        metric_registry: MetricRegistry,
        trigger_manager: AnalysisTriggerManager  # ← NEW
    ):
        self.metric_registry = metric_registry
        self.trigger_manager = trigger_manager

    def complete_agent_execution(self, execution: AgentExecution):
        # 1. Store execution
        self.db.save(execution)

        # 2. Compute custom metrics
        metrics = self.metric_registry.collect_all(execution)
        store_custom_metrics(execution.id, metrics)

        # 3. Check if analysis should trigger
        self.trigger_manager.on_execution_complete(execution.agent_name)
        # ↑ Automatically triggers PerformanceAnalyzer when ready
```

### Example Scenarios

**Scenario 1: High-traffic (parallel) - Fast trigger**
```
10:00 AM - Execution 1 completes
10:05 AM - Execution 50 completes (parallel agents!)
10:10 AM - Execution 100 completes
         → Triggers analysis after 10 minutes ✅

Instead of waiting 24 hours!
```

**Scenario 2: Low-traffic - Wait for sufficient data**
```
Day 1 - 10 executions → Too soon (10/100)
Day 5 - 80 executions → Still waiting (80/100)
Day 7 - 95 executions → Force trigger (max_interval_exceeded)
         → Better than analyzing with 10 executions!
```

**Scenario 3: Burst detection**
```
Normal: 10 exec/hour
10:00 - Load test starts!
10:01 - 200 executions/minute
10:02 - 300 executions/minute
      → Burst detected! Triggers immediately ✅

Catches issues during load testing!
```

### Benefits

| Benefit | Description |
|---------|-------------|
| **Faster feedback** | High-traffic agents analyzed in minutes |
| **Parallel-aware** | Adapts to parallel execution speed |
| **Data-driven** | Waits for sufficient data, not arbitrary time |
| **Burst responsive** | Detects unusual traffic patterns |
| **Resource efficient** | Doesn't analyze when insufficient data |
| **Predictable** | max_interval ensures regular analysis |

### Configuration Examples

```python
# High-traffic production agent
AnalysisTriggerConfig(
    min_executions=200,
    target_executions=500,
    min_interval_hours=1,
    max_interval_hours=24,
    enable_burst_detection=True
)

# Low-traffic experimental agent
AnalysisTriggerConfig(
    min_executions=50,
    target_executions=100,
    min_interval_hours=6,
    max_interval_hours=336,  # 2 weeks
    enable_burst_detection=False
)

# Development/testing
AnalysisTriggerConfig(
    min_executions=10,
    target_executions=20,
    min_interval_hours=0.1,  # 6 minutes
    max_interval_hours=4,
    enable_burst_detection=True
)
```

---

## 4. Pattern Extractors (How to Learn)

### Status: 🚧 Pending Discussion

**Question:** How does M5 learn what works and what doesn't from execution history?

**To Discuss:**
- Frequent itemset mining (association rules)
- Time-series trend detection
- Clustering similar executions
- ML-based pattern discovery
- Domain-specific pattern recognition

---

## 4. Experiment Types (How to Test)

### Status: 🚧 Pending Discussion

**Question:** How does M5 run experiments to validate improvements?

**To Discuss:**
- A/B testing (fixed traffic split)
- Multi-armed bandits (Thompson Sampling)
- Sequential testing (SPRT early stopping)
- Contextual bandits (context-aware)
- Multi-objective optimization

---

## 5. Rollout Strategies (How to Deploy)

### Status: 🚧 Pending Discussion

**Question:** How does M5 deploy winning configurations safely?

**To Discuss:**
- Gradual rollout (10→25→50→100%)
- Canary deployment
- Blue-green deployment
- Geographic rollout
- User segment rollout

---

## Design Patterns

### Common Architecture Across All Components

```python
# 1. Abstract interface
class PluginInterface(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def core_method(self, *args) -> Any:
        pass

    @abstractmethod
    def is_applicable(self, context) -> bool:
        pass

# 2. Registry for swapping
class PluginRegistry:
    def __init__(self):
        self._plugins = {}

    def register(self, plugin: PluginInterface):
        self._plugins[plugin.name] = plugin

    def get(self, name: str) -> PluginInterface:
        return self._plugins[name]

# 3. Built-in implementations
- Ship with 3-5 common plugins
- Cover 80% of use cases

# 4. User extensions
- Users add domain-specific plugins
- Register via simple API
- No core code changes needed
```

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-02-01 | Metric Collectors: CRITICAL priority | Different agents need different metrics. Must be extensible from day 1. |
| 2026-02-01 | Improvement Strategies: CRITICAL priority | Different problems need different solutions. Domain-specific optimizations essential. |
| 2026-02-01 | Hybrid Trigger System: CRITICAL priority | Time-based alone is too rigid. Need event-driven triggers that adapt to execution patterns and parallel workloads. |
| 2026-02-01 | Use plugin architecture pattern | Consistent interface + registry pattern across all components for ease of use. |
| 2026-02-01 | Compute metrics once, query with SQL | MetricCollectors compute custom metrics after execution and store in DB. PerformanceAnalyzer queries DB directly for fast aggregation. |

---

## Next Steps

1. ✅ Discuss and decide on Pattern Extractors modularity
2. ✅ Discuss and decide on Experiment Types modularity
3. ✅ Discuss and decide on Rollout Strategies modularity
4. Update M5 implementation plan with modular architecture
5. Define Phase 0: Plugin architecture foundation

---

## Open Questions

- Should all 5 modularity points use the same registry pattern? **(Likely yes for consistency)**
- Do we need a meta-registry (registry of registries)?
- How do plugins discover each other (dependencies between plugins)?
- Versioning strategy for plugin interfaces?
- How to handle plugin conflicts (two collectors for same metric)?
- What happens when multiple strategies apply to same problem? Run all? Pick best? Ensemble?
- How to handle backwards compatibility when plugin interfaces change?

---

## Conversation Summary (2026-02-01)

### What We've Designed (3/6 Components)

**1. Metric Collectors ✅**
- **Problem:** Different tasks need different quality metrics (code quality, factual accuracy, customer satisfaction, etc.)
- **Solution:** Pluggable MetricCollector interface + MetricRegistry
- **Key Insight:** Compute metrics ONCE after execution, store in `custom_metrics` table, query with SQL during analysis (not Python loops!)
- **Built-ins:** SuccessRate, Cost, Duration, Tokens
- **User extensions:** QualityScore, CodeComplexity, FactualAccuracy, etc.

**2. Improvement Strategies ✅**
- **Problem:** Different problems need different solutions (cost reduction, quality improvement, speed optimization)
- **Solution:** Pluggable ImprovementStrategy interface + StrategyRegistry
- **Key Insight:** Strategies receive learned patterns and generate multiple config variants to test
- **Built-ins:** PromptTuning, CostReduction, ParameterTuning, SpeedOptimization
- **User extensions:** LegalDocumentStrategy, MedicalComplianceStrategy, etc.
- **Integration:** ImprovementDetector asks strategies to generate variants when problems detected

**3. Hybrid Trigger System ✅**
- **Problem:** Time-based scheduling is too rigid (wastes time for high-traffic, insufficient data for low-traffic)
- **Solution:** Event-driven triggers based on execution count + time bounds
- **Key Insight:** Parallel execution gets results faster - system adapts automatically
- **Triggers:** min_executions (100), target_executions (200), min_interval (1h), max_interval (7d), burst_detection (500+ exec in 10min)
- **Integration:** ExecutionTracker calls TriggerManager after each execution to check if analysis should run

**2.5. PerformanceAnalyzer (The "WATCH" Component) ✅**
- **Problem:** Need to aggregate metrics efficiently without recomputing
- **Solution:** Query database with SQL (fast!), not Python loops
- **Execution Model:** Discrete/batch (not continuous) - hourly or triggered by Hybrid System
- **Output:** AgentPerformanceProfile with aggregated metrics
- **Consumers:** ImprovementDetector (compares profiles), Dashboards, Alerts

### What's Still Pending (3/6 Components)

**4. Pattern Extractors 🚧**
- How M5 learns from execution history
- Association rules, trend detection, clustering, ML-based
- Input to Improvement Strategies

**5. Experiment Types 🚧**
- A/B testing, Multi-armed bandits, Sequential testing
- How M5 validates improvements

**6. Rollout Strategies 🚧**
- Gradual rollout, Canary, Blue-green
- How M5 deploys winners safely

### Key Architectural Patterns

All components follow same pattern for consistency:

```python
# 1. Abstract interface
class Plugin(ABC):
    @property
    @abstractmethod
    def name(self) -> str: pass

    @abstractmethod
    def core_method(self, *args): pass

    @abstractmethod
    def is_applicable(self, context) -> bool: pass

# 2. Registry for swapping
class PluginRegistry:
    def register(self, plugin: Plugin): ...
    def get(self, name: str) -> Plugin: ...
    def find_applicable(self, context) -> List[Plugin]: ...

# 3. Built-in implementations (3-5 common ones)
# 4. User extensions (domain-specific)
```

### Tomorrow's Agenda

1. **Pattern Extractors** - Design how M5 learns patterns from execution history
2. **Experiment Types** - Design A/B testing and multi-armed bandit implementation
3. **Rollout Strategies** - Design gradual deployment with safety checks
4. **Update main M5 plan** - Incorporate all modular components into implementation phases
5. **Phase 0 definition** - Define "build plugin architecture foundation" phase

### Critical Design Decisions Made

| Decision | Rationale |
|----------|-----------|
| **Compute metrics once, store, query** | Avoid recomputing expensive metrics; SQL aggregation 100x faster |
| **Discrete analysis, not continuous** | Need statistical significance (50-100 samples); batch queries more efficient |
| **Hybrid triggers (time + cycle)** | Adapts to traffic patterns; parallel execution gets results faster |
| **Pluggable everything** | Long-term vision requires extensibility from day 1 |
| **Same pattern for all plugins** | Consistency makes system easier to understand and extend |
| **Database-first architecture** | Query DB with SQL, don't load everything into Python |

---

## M5 Implementation Roadmap

### Overview: Phases → Milestones → Components

M5 implementation is organized into milestones, each delivering incremental value. Each milestone consists of multiple implementation phases that build specific M5 components.

```
M5 MILESTONE 1 (MVP) - Core Self-Improvement Loop
├─ Phase 0: Foundation
├─ Phase 1: MetricCollectors (Modularity Point #1)
├─ Phase 2: PerformanceAnalyzer (WATCH)
├─ Phase 3: ImprovementStrategies (Modularity Point #2) + ImprovementDetector (DETECT + PLAN)
├─ Phase 4: ExperimentOrchestrator (TEST)
├─ Phase 5: ConfigDeployer (DEPLOY)
├─ Phase 6: Integration (M5SelfImprovementLoop)
└─ Phase 7: Validation (Real scenario test)

M5 MILESTONE 2 - Autonomous Triggering
├─ Phase 8-9: Additional Strategies
└─ Phase 10: Hybrid Triggers (Modularity Point #3)

M5 MILESTONE 3 - Pattern Learning
├─ Phase 11: Pattern Extractors (Modularity Point #4)
└─ Phase 12: Pattern-driven Strategy Enhancement

M5 MILESTONE 4 - Advanced Experimentation
├─ Phase 13: Experiment Types (Modularity Point #5)
└─ Phase 14: Multi-objective Statistical Analysis

M5 MILESTONE 5 - Production Deployment
├─ Phase 15: Rollout Strategies (Modularity Point #6)
└─ Phase 16: Monitoring & Alerts
```

---

### M5 Milestone 1: MVP - Single-Strategy Self-Improvement Loop

**Goal:** Prove M5 works end-to-end with minimal features

**Use Case:** Find best Ollama model for structured data extraction task

#### Phase 0: Foundation
**Dependencies:** M1 Observability (prerequisite)

```
✅ Infrastructure Setup
   ├─ M1 database schema (agent_executions table)
   ├─ ExecutionTracker component
   ├─ Basic metrics (cost, duration, status)
   ├─ AgentConfig data model
   └─ AgentExecution data model

✅ Ollama Setup
   ├─ Install Ollama locally
   ├─ Pull test models:
   │   ├─ phi3:mini (small/fast)
   │   ├─ llama3.1:8b (medium/balanced)
   │   ├─ mistral:7b (medium/quality)
   │   └─ qwen2.5:32b (large/accurate)
   └─ Verify models work
```

#### Phase 1: Agent + Quality Metric
**Goal:** Build the agent we'll optimize + measure quality

**Deliverables:**

```python
# 1. MetricCollector Interface (Modularity Point #1)
class MetricCollector(ABC):
    @property
    @abstractmethod
    def metric_name(self) -> str: pass

    @abstractmethod
    def collect(self, execution: AgentExecution) -> Optional[float]: pass

    @abstractmethod
    def is_applicable(self, execution: AgentExecution) -> bool: pass

# 2. MetricRegistry
class MetricRegistry:
    def register(self, collector: MetricCollector): ...
    def collect_all(self, execution: AgentExecution) -> Dict[str, float]: ...

# 3. First Custom Collector
class ExtractionQualityCollector(MetricCollector):
    """Measures field-level accuracy for structured extraction."""
    metric_name = "extraction_quality"

    def collect(self, execution):
        # Calculate field accuracy: correct_fields / total_fields
        return field_accuracy_score  # 0.0 to 1.0

# 4. ProductExtractorAgent (test agent)
class ProductExtractorAgent:
    """Extract structured product info from unstructured text."""
    def extract(self, description: str) -> dict:
        # Uses Ollama for inference
        # Returns JSON: {product_name, price, category, in_stock, rating}

# 5. Test Dataset
PRODUCT_TEST_CASES = [
    {"description": "...", "ground_truth": {...}},
    # 50 test cases total
]

# 6. Database Schema Extension
CREATE TABLE custom_metrics (
    id TEXT PRIMARY KEY,
    workflow_execution_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    metric_metadata JSON,
    recorded_at TIMESTAMP NOT NULL,
    FOREIGN KEY (workflow_execution_id) REFERENCES workflow_executions(id)
);
```

**Validation:**
- Run ProductExtractorAgent 50 times
- Verify ExtractionQualityCollector stores quality scores in DB
- Can query metrics with SQL

**Output:** Working agent with measurable quality metric, extensible MetricCollector system

---

#### Phase 2: Performance Analysis
**Goal:** Detect when quality could be better

**Deliverables:**

```python
# 1. PerformanceAnalyzer (the "WATCH" component)
class PerformanceAnalyzer:
    def analyze_agent_performance(
        self,
        agent_name: str,
        window_hours: int = 168
    ) -> AgentPerformanceProfile:
        """
        Query DB for metrics using SQL (fast!).
        Aggregate: mean, std, p95 for all metrics.
        """

    def get_baseline(
        self,
        agent_name: str,
        window_days: int = 30
    ) -> AgentPerformanceProfile:
        """Historical baseline for comparison."""

# 2. AgentPerformanceProfile data model
@dataclass
class AgentPerformanceProfile:
    agent_name: str
    window_start: datetime
    window_end: datetime
    total_executions: int
    metrics: Dict[str, Dict[str, float]]  # {metric_name: {mean, std, p95}}
    created_at: datetime

# 3. Simple Trigger (manual for MVP)
def run_analysis_manually(agent_name: str):
    """Manual trigger - run on demand."""
    analyzer = PerformanceAnalyzer(db)
    profile = analyzer.analyze_agent_performance(agent_name)
    store_profile(profile)
```

**Validation:**
- Run agent 100 times with llama3.1:8b
- Analyze performance: avg_quality = 0.72
- Store as baseline profile

**Output:** Can analyze agent performance, create baselines, compare current vs historical

---

#### Phase 3: Problem Detection + Strategy
**Goal:** Detect quality issues and generate model variants

**Deliverables:**

```python
# 1. ImprovementDetector (the "DETECT" component)
class ImprovementDetector:
    def detect_improvement(
        self,
        agent_name: str
    ) -> Optional[ImprovementProposal]:
        """
        Compare current vs baseline.
        If problem detected, ask strategy to generate solutions.
        """

    def _detect_problems(
        self,
        current: AgentPerformanceProfile,
        baseline: AgentPerformanceProfile
    ) -> List[Dict]:
        """
        Simple threshold detection:
        - quality_low: current < baseline * 0.9
        - cost_too_high: current > baseline * 1.3
        - too_slow: current > baseline * 1.5
        """

# 2. ImprovementStrategy Interface (Modularity Point #2)
class ImprovementStrategy(ABC):
    @property
    @abstractmethod
    def name(self) -> str: pass

    @abstractmethod
    def generate_variants(
        self,
        current_config: AgentConfig,
        patterns: List[LearnedPattern]
    ) -> List[AgentConfig]: pass

    @abstractmethod
    def is_applicable(self, problem_type: str) -> bool: pass

# 3. StrategyRegistry
class StrategyRegistry:
    def register(self, strategy: ImprovementStrategy): ...
    def get(self, name: str) -> ImprovementStrategy: ...
    def find_applicable(self, problem_type: str) -> List[ImprovementStrategy]: ...

# 4. OllamaModelSelectionStrategy (first strategy!)
class OllamaModelSelectionStrategy(ImprovementStrategy):
    """Test different Ollama models to find best performer."""

    name = "ollama_model_selection"

    OLLAMA_MODELS = [
        {"name": "phi3:mini", "size": "3.8B", "expected_quality": "medium"},
        {"name": "llama3.1:8b", "size": "8B", "expected_quality": "high"},
        {"name": "mistral:7b", "size": "7B", "expected_quality": "high"},
        {"name": "qwen2.5:32b", "size": "32B", "expected_quality": "highest"},
    ]

    def generate_variants(self, current_config, patterns):
        """Generate 3 model variants across size tiers."""
        # Returns configs for: small, medium, large models

    def is_applicable(self, problem_type):
        return problem_type in ["quality_low", "initial_optimization"]

# 5. ImprovementProposal data model
@dataclass
class ImprovementProposal:
    id: str
    agent_name: str
    problem_type: str
    problem_severity: float
    strategy_name: str
    current_config: AgentConfig
    variant_configs: List[AgentConfig]
    expected_improvement: float
    created_at: datetime
```

**Validation:**
- Detector finds quality_low problem (0.72 < 0.85)
- Strategy generates variants: phi3:mini, mistral:7b, qwen2.5:32b
- Proposal created with 3 variant configs

**Output:** Can detect problems and generate solutions, extensible Strategy system

---

#### Phase 4: Experiment Framework
**Goal:** A/B test multiple models and pick winner

**Deliverables:**

```python
# 1. ExperimentOrchestrator (the "TEST" component)
class ExperimentOrchestrator:
    def create_experiment(
        self,
        proposal: ImprovementProposal
    ) -> Experiment:
        """
        Create A/B/C/D test with control + variants.
        Split traffic evenly (e.g., 25/25/25/25 for 4 groups).
        """

    def assign_variant(self, execution_id: str) -> str:
        """Hash-based assignment (deterministic, reproducible)."""

    def is_complete(self, experiment_id: str) -> bool:
        """Check if target executions reached for all groups."""

# 2. Experiment Execution
class Experiment:
    def record_execution(
        self,
        variant_id: str,
        quality: float,
        speed: float
    ): ...

    def get_results(self) -> Dict[str, ExperimentResults]: ...

# 3. StatisticalAnalyzer
class StatisticalAnalyzer:
    def analyze_experiment(
        self,
        experiment: Experiment
    ) -> ExperimentAnalysis:
        """
        Compare variants vs control.
        Use t-test for statistical significance.
        Pick winner based on composite score: quality (primary).
        """

    def get_winner(
        self,
        experiment: Experiment
    ) -> Optional[VariantConfig]:
        """Return winning config if statistically significant."""

# 4. Database Schema
CREATE TABLE experiments (
    id TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    status TEXT NOT NULL,  -- 'running', 'completed', 'failed'
    control_config JSON NOT NULL,
    variant_configs JSON NOT NULL,
    created_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP
);

CREATE TABLE experiment_results (
    id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL,
    variant_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    quality_score REAL,
    speed_seconds REAL,
    recorded_at TIMESTAMP NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES experiments(id)
);
```

**Validation:**
- Run 4-way experiment (control + 3 variants)
- 50 executions per variant = 200 total
- Verify winner = highest quality model (qwen2.5:32b)

**Output:** Can run A/B tests and pick winners using statistical analysis

---

#### Phase 5: Deployment
**Goal:** Deploy winning configuration

**Deliverables:**

```python
# 1. ConfigDeployer (the "DEPLOY" component)
class ConfigDeployer:
    def deploy(
        self,
        agent_name: str,
        new_config: AgentConfig
    ):
        """
        Update agent config in database.
        Agent uses new config on next execution.
        Store previous config for rollback.
        """

    def rollback(
        self,
        agent_name: str
    ):
        """Revert to previous config if regression detected."""

# 2. Simple Deployment (MVP)
# - 100% immediate deployment (no gradual rollout yet)
# - Just swap the config atomically
# - Monitor next N executions for regressions

# 3. Database Schema
CREATE TABLE config_deployments (
    id TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL,
    previous_config JSON NOT NULL,
    new_config JSON NOT NULL,
    experiment_id TEXT,
    deployed_at TIMESTAMP NOT NULL,
    deployed_by TEXT,
    rollback_at TIMESTAMP,
    FOREIGN KEY (experiment_id) REFERENCES experiments(id)
);
```

**Validation:**
- Deploy winner (qwen2.5:32b)
- Run 50 more extractions
- Verify quality improved (0.72 → 0.91) and sustained

**Output:** Can deploy winning configs safely with rollback capability

---

#### Phase 6: End-to-End Integration
**Goal:** Wire everything together into M5 loop

**Deliverables:**

```python
# 1. M5SelfImprovementLoop (orchestrates all components)
class M5SelfImprovementLoop:
    """Complete M5 self-improvement loop."""

    def __init__(self, db):
        self.performance_analyzer = PerformanceAnalyzer(db)
        self.improvement_detector = ImprovementDetector(
            performance_analyzer=self.performance_analyzer,
            strategy_registry=StrategyRegistry()
        )
        self.experiment_orchestrator = ExperimentOrchestrator(db)
        self.config_deployer = ConfigDeployer(db)

    def run_analysis(self):
        """WATCH: Analyze all agents, detect problems."""
        agents = db.get_all_agent_names()
        for agent_name in agents:
            profile = self.performance_analyzer.analyze_agent_performance(agent_name)
            store_profile(profile)

    def run_optimization(self):
        """DETECT + PLAN: Find problems, create experiments."""
        agents = db.get_all_agent_names()
        for agent_name in agents:
            proposal = self.improvement_detector.detect_improvement(agent_name)
            if proposal:
                experiment = self.experiment_orchestrator.create_experiment(proposal)
                experiment.start()

    def check_experiments(self):
        """TEST + DEPLOY: Check if experiments done, deploy winners."""
        completed = db.get_completed_experiments()
        for experiment in completed:
            winner = experiment.get_winner()
            if winner and winner.is_better_than_control():
                self.config_deployer.deploy(experiment.agent_name, winner.config)

# 2. Manual Orchestration (MVP)
# Run M5 manually via CLI:
# $ python -m m5.cli analyze          # Run WATCH
# $ python -m m5.cli optimize         # Run DETECT + PLAN
# $ python -m m5.cli check-experiments # Run TEST + DEPLOY
```

**Validation:**
- Run full loop manually: analyze → optimize → check-experiments
- Verify each component works in sequence

**Output:** Complete M5 loop working end-to-end

---

#### Phase 7: Real Scenario Validation
**Goal:** Prove M5 works with realistic scenario

**Scenario: "Find Best Ollama Model for Product Extraction"**

```
Step 1: Baseline Period
├─ Run 100 extractions with llama3.1:8b (random choice)
├─ Record quality = 0.72 (72% field accuracy)
└─ Store as baseline

Step 2: Trigger M5 Analysis
├─ M5 analyzes performance
├─ Detects: quality_low (0.72 < 0.85 baseline)
└─ Problem severity: 0.15 (15% gap)

Step 3: Strategy Generates Solutions
├─ OllamaModelSelectionStrategy activated
├─ Generates variants:
│   ├─ phi3:mini (small/fast)
│   ├─ mistral:7b (medium/quality)
│   └─ qwen2.5:32b (large/accurate)
└─ ImprovementProposal created

Step 4: Experiment Runs
├─ ExperimentOrchestrator creates 4-way test
├─ 50 extractions per variant = 200 total
├─ Results:
│   ├─ Control (llama3.1:8b): quality=0.72, speed=2.3s
│   ├─ Variant A (phi3:mini): quality=0.65, speed=0.8s
│   ├─ Variant B (mistral:7b): quality=0.78, speed=1.9s
│   └─ Variant C (qwen2.5:32b): quality=0.91, speed=5.2s ⭐
└─ Winner: qwen2.5:32b

Step 5: Deployment
├─ ConfigDeployer deploys qwen2.5:32b
├─ Quality: 0.72 → 0.91 (+26% improvement!)
└─ Trade-off accepted: Speed 2.3s → 5.2s (acceptable for quality gain)

Step 6: Validation
├─ Run 100 more extractions with qwen2.5:32b
├─ Verify quality sustained at 0.90+
└─ SUCCESS: M5 automatically found best model! 🎉
```

**Success Metrics:**
```
✅ Quality improved: 0.72 → 0.91 (+26%)
✅ Statistically significant (p < 0.05)
✅ M5 ran automatically (no manual intervention after initial trigger)
✅ Best model discovered through experimentation (not guessing)
✅ Improvement sustained over 100+ executions
```

**Output:** Proven M5 system that automatically improves agents

---

### M5 Milestone 1 Deliverables Summary

**Components Built:**
```
✅ WATCH: PerformanceAnalyzer
✅ DETECT: ImprovementDetector
✅ PLAN: ImprovementStrategy (OllamaModelSelectionStrategy)
✅ TEST: ExperimentOrchestrator
✅ DEPLOY: ConfigDeployer
✅ ORCHESTRATE: M5SelfImprovementLoop
```

**Modularity Points Implemented:**
```
✅ #1: MetricCollectors (interface + registry + 1 collector)
✅ #2: ImprovementStrategies (interface + registry + 1 strategy)
```

**What Works:**
- End-to-end self-improvement loop
- Extensible metric system (can add more collectors)
- Extensible strategy system (can add more strategies)
- A/B testing with statistical analysis
- Safe deployment with rollback
- Proven with real scenario

**What's NOT in Milestone 1 (Future):**
- ❌ Hybrid triggers (manual trigger only)
- ❌ Pattern learning (strategies don't use patterns yet)
- ❌ Advanced experiments (just basic A/B test)
- ❌ Gradual rollout (100% immediate only)
- ❌ Automatic scheduling (manual CLI for now)

**Timeline:** No specific timeline - complete phases in order

---

### M5 Milestone 2: Autonomous Triggering

**Goal:** M5 runs automatically without manual intervention

#### Phase 8-9: Additional Strategies

```python
# Add second strategy: CostReductionStrategy (if tracking API costs)
class CostReductionStrategy(ImprovementStrategy):
    def generate_variants(self, current_config, patterns):
        # Reduce max_tokens, enable caching, use cheaper model

# Add third strategy: ParameterTuningStrategy
class ParameterTuningStrategy(ImprovementStrategy):
    def generate_variants(self, current_config, patterns):
        # Adjust temperature, top_p, etc.
```

**Validation:** StrategyRegistry works with multiple strategies, picks best per problem

#### Phase 10: Hybrid Trigger System (Modularity Point #3)

```python
class AnalysisTriggerManager:
    """Event-driven triggers based on execution count + time bounds."""

    def on_execution_complete(self, agent_name: str):
        """Called after EVERY agent execution."""
        should_trigger, reason = self.should_trigger_analysis(agent_name)
        if should_trigger:
            self._trigger_analysis(agent_name, reason)

    def should_trigger_analysis(self, agent_name: str) -> Tuple[bool, str]:
        """Decide based on multiple criteria."""
        # Check 1: Min interval (rate limiting)
        # Check 2: Max interval (force analysis)
        # Check 3: Target executions reached
        # Check 4: Burst detected
        # Check 5: Sufficient new data

# Integration with ExecutionTracker
class ExecutionTracker:
    def complete_agent_execution(self, execution: AgentExecution):
        # Store execution
        # Compute custom metrics
        # Check if analysis should trigger ← NEW!
        self.trigger_manager.on_execution_complete(execution.agent_name)
```

**Deliverables:**
- Automatic triggering (no manual CLI needed)
- Adapts to traffic patterns (parallel execution)
- Burst detection for load tests
- Time + cycle based hybrid triggers

**Output:** M5 runs autonomously, optimizes continuously

---

### M5 Milestone 3: Pattern Learning

**Goal:** Learn from execution history to make smarter optimizations

#### Phase 11: Pattern Extractors (Modularity Point #4)

```python
class PatternLearner:
    """Learn patterns from execution history."""

    def extract_patterns(self, agent_name: str) -> List[LearnedPattern]:
        """
        Mine execution logs for patterns:
        - Association rules (frequent itemsets)
        - Time-series trends
        - Success/failure correlations
        """

@dataclass
class LearnedPattern:
    pattern_type: str  # "association", "trend", "correlation"
    description: str   # "include_examples_success"
    support: int       # How many times seen
    confidence: float  # How reliable (0-1)
    evidence: Dict     # Supporting data
```

#### Phase 12: Pattern-driven Strategy Enhancement

```python
# Strategies now USE patterns to make smarter decisions
class PromptTuningStrategy(ImprovementStrategy):
    def generate_variants(self, current_config, patterns):
        variants = []

        # Pattern-driven decisions!
        if patterns.find("include_examples_success", confidence > 0.8):
            variant = current_config.copy()
            variant["prompt"]["include_examples"] = True
            variant["prompt"]["num_examples"] = 3
            variants.append(variant)

        return variants
```

**Output:** Strategies learn from history, optimize based on learned patterns

---

### M5 Milestone 4: Advanced Experimentation

**Goal:** Smarter experiments that converge faster

#### Phase 13: Experiment Types (Modularity Point #5)

```python
class ExperimentRegistry:
    """Pluggable experiment types."""

# Multiple experiment types
class ABTestExperiment: ...           # Fixed traffic split
class ThompsonSamplingExperiment: ... # Multi-armed bandit
class SequentialTestExperiment: ...   # Early stopping (SPRT)
class ContextualBanditExperiment: ... # Context-aware allocation
```

**Output:** Faster convergence, multi-objective optimization

---

### M5 Milestone 5: Production Deployment

**Goal:** Production-safe rollouts with monitoring

#### Phase 15: Rollout Strategies (Modularity Point #6)

```python
class RolloutRegistry:
    """Pluggable rollout strategies."""

class GradualRolloutStrategy: ...  # 10% → 50% → 100%
class CanaryDeploymentStrategy: ... # Single canary instance
class GeographicRolloutStrategy: ... # Region by region
```

#### Phase 16: Monitoring & Alerts

```python
class RegressionDetector:
    """Real-time degradation detection."""

class AutoRollback:
    """Automatic rollback on regression."""
```

**Output:** Production-ready M5 with safe deployments

---

### Complete Modularity Points Coverage

| Modularity Point | Milestone | Status |
|------------------|-----------|--------|
| #1: MetricCollectors | M1 | ✅ Designed & Decided |
| #2: ImprovementStrategies | M1 | ✅ Designed & Decided |
| #3: Hybrid Triggers | M2 | ✅ Designed & Decided |
| #4: Pattern Extractors | M3 | 🚧 Pending |
| #5: Experiment Types | M4 | 🚧 Pending |
| #6: Rollout Strategies | M5 | 🚧 Pending |

---

### Current Focus

**Building: M5 Milestone 1 (MVP)**
- Phases 0-7
- Core self-improvement loop
- 2 modularity points (MetricCollectors + Strategies)
- Ollama model selection use case
- Proven end-to-end

**Next: M5 Milestone 2**
- Autonomous triggering
- Additional strategies
- No manual intervention needed

---

**Document Status:** Living document capturing M5 architectural discussions
**Last Updated:** 2026-02-01
**Progress:** 3/6 components designed (50%), M1 roadmap complete
**Current Milestone:** M5 Milestone 1 (Phases 0-7)
**Next Session:** Implement Phase 1 (Agent + Quality Metric)
