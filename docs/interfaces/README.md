# Interface Documentation

This directory contains comprehensive documentation for all public interfaces in the Meta-Autonomous Framework.

## Organization

### [Core Interfaces](./core/)
Foundational interfaces for the main system components:
- **[Agent Interface](./core/agent_interface.md)** - BaseAgent, StandardAgent, AgentFactory
- **[LLM Provider Interface](./core/llm_provider_interface.md)** - BaseLLMProvider, Ollama, OpenAI, Anthropic
- **[Tool Interface](./core/tool_interface.md)** - BaseTool, ToolRegistry, built-in tools

### [Data Models](./models/)
Configuration and observability data structures:
- **[Config Schemas](./models/config_schema.md)** - WorkflowConfig, StageConfig, AgentConfig, ToolConfig
- **[Observability Models](./models/observability_models.md)** - Database schema, execution tracking models

## Key Concepts

### Interface-Driven Architecture
Every major component has an abstract interface:
- Enables radical modularity and extensibility
- Allows multiple implementations (e.g., different LLM providers)
- Provides clear contracts for custom implementations
- Facilitates testing with mocks/stubs

### Configuration-Driven
All interfaces are configured via YAML:
- Declarative configuration for agents, tools, workflows
- Environment-specific overrides
- Validation via Pydantic schemas
- See [Configuration Guide](../../docs/CONFIGURATION.md) (coming soon)

## Adding Custom Implementations

### Custom Agent
1. Extend `BaseAgent` from [Agent Interface](./core/agent_interface.md)
2. Implement required methods: `execute()`, `get_capabilities()`
3. Register with `AgentFactory.register()`
4. Add configuration schema
5. Write tests

### Custom Tool
1. Extend `BaseTool` from [Tool Interface](./core/tool_interface.md)
2. Implement: `execute()`, `get_parameters_schema()`
3. Add safety checks
4. Register with `ToolRegistry`
5. Write tests

### Custom LLM Provider
1. Extend `BaseLLMProvider` from [LLM Provider Interface](./core/llm_provider_interface.md)
2. Implement: `generate()`, `generate_stream()`
3. Override `estimate_cost()` with provider pricing
4. Add to provider map
5. Write tests

## Related Documentation

- [System Overview](../architecture/SYSTEM_OVERVIEW.md) - High-level architecture
- [Documentation Index](../INDEX.md) - All documentation
- [API Reference](../API_REFERENCE.md) - (coming soon)
- [Contributing Guide](../CONTRIBUTING.md) - (coming soon)
