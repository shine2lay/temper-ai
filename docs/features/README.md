# Feature Documentation

Comprehensive guides for major framework features and capabilities.

## Organization

### [Collaboration Features](./collaboration/)
Multi-agent coordination and collaboration strategies:
- **[Multi-Agent Collaboration](./collaboration/multi_agent_collaboration.md)** - Overview of M3 collaboration system
- **[Collaboration Strategies](./collaboration/collaboration_strategies.md)** - Voting, consensus, debate, hierarchical strategies

**Key Capabilities:**
- Parallel agent execution (2-3x speedup)
- Consensus and voting mechanisms
- Multi-round debate with convergence detection
- Merit-weighted conflict resolution
- Strategy composition and fallback chains

**Use Cases:**
- Research tasks requiring diverse perspectives
- Decision-making with multiple criteria
- Complex problems needing specialist agents
- Quality improvement through peer review

---

### [Execution Features](./execution/)
Workflow execution and engine abstraction:
- **[Execution Engine Architecture](./execution/execution_engine_architecture.md)** - M2.5 engine abstraction design
- **[Custom Engine Guide](./execution/custom_engine_guide.md)** - Building custom execution engines

**Key Capabilities:**
- Multi-engine support (LangGraph, custom engines)
- Engine registry and factory pattern
- Workflow compilation and optimization
- State management and checkpointing
- Execution tracing and observability

**Use Cases:**
- Switching execution backends
- Custom workflow engines for specialized domains
- Performance optimization
- Testing with mock engines

---

### [Observability Features](./observability/)
Execution tracking, visualization, and analytics:
- **[Gantt Visualization](./observability/GANTT_VISUALIZATION.md)** - Timeline visualization for workflow execution

**Key Capabilities:**
- Hierarchical execution tracking (workflow → stage → agent → LLM/tool)
- Real-time and historical trace visualization
- Token and cost tracking
- Performance analytics
- Gantt chart generation for timing analysis

**Use Cases:**
- Debugging workflow failures
- Analyzing performance bottlenecks
- Tracking LLM costs
- Understanding agent behavior
- Reporting and analytics

---

## Feature Status

### ✅ Completed Features
- **M1**: Core agent system, tools, observability foundation
- **M2**: Workflow orchestration with LangGraph
- **M2.5**: Execution engine abstraction layer
- **M3**: Multi-agent collaboration strategies

### 🚧 In Progress
- **M4**: Safety and governance system
  - Safety policies (blast radius, secret detection, rate limiting)
  - Approval workflows
  - Rollback mechanisms

### 📋 Planned
- **M5**: Self-improvement loop
- **M6**: Multiple product types

See [Roadmap](../ROADMAP.md) for detailed feature planning.

---

## Related Documentation

- [Documentation Index](../INDEX.md) - All documentation
- [Interfaces](../interfaces/) - Core interfaces and data models
- [Architecture](../architecture/) - System architecture
- [Milestones](../milestones/) - Milestone completion reports
- [Quick Start](../QUICK_START.md) - Getting started guide

---

## Feature Request Process

To request a new feature:

1. **Check existing features**: Review this directory and milestone reports
2. **Open discussion**: Create issue in repository
3. **Propose design**: Follow architecture decision record (ADR) format
4. **Get approval**: Discuss with maintainers
5. **Implement**: Follow contributing guidelines
6. **Document**: Add documentation to appropriate features/ subdirectory
