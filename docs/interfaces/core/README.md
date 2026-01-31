# Core Interfaces

Foundational interfaces for the main system components.

## Interfaces

### [Agent Interface](./agent_interface.md)
**Purpose:** Define how agents execute tasks and interact with the system

**Key Components:**
- `BaseAgent` - Abstract base class for all agents
- `StandardAgent` - Default implementation with LLM + tool execution
- `AgentFactory` - Factory pattern for creating agent instances

**Capabilities:**
- LLM-powered reasoning and decision making
- Tool execution with safety checks
- Observability and tracking
- Configurable behavior via YAML

**Use Cases:**
- Research agents for information gathering
- Synthesis agents for combining data
- Specialized agents for domain-specific tasks
- Custom agents with unique behaviors

---

### [LLM Provider Interface](./llm_provider_interface.md)
**Purpose:** Abstract LLM provider integration for multi-provider support

**Key Components:**
- `BaseLLMProvider` - Abstract base class for all providers
- `OllamaProvider` - Local LLM support (llama, mistral, etc.)
- `OpenAIProvider` - OpenAI API integration
- `AnthropicProvider` - Claude API integration

**Capabilities:**
- Unified API across all providers
- Streaming and non-streaming generation
- Cost estimation and token tracking
- Retry logic with exponential backoff
- Context window management

**Use Cases:**
- Switch between providers without code changes
- Cost optimization (use cheaper models for simple tasks)
- Privacy control (local Ollama for sensitive data)
- Fallback chains (try OpenAI, fall back to Ollama)

---

### [Tool Interface](./tool_interface.md)
**Purpose:** Define how tools are registered, validated, and executed

**Key Components:**
- `BaseTool` - Abstract base class for all tools
- `ToolRegistry` - Central registry for tool discovery
- Built-in tools: Calculator, FileWriter, WebScraper

**Capabilities:**
- JSON schema generation for LLM consumption
- Parameter validation
- Execution tracking and observability
- Safety checks and sandboxing
- Auto-discovery from directories

**Use Cases:**
- File system operations (read, write, search)
- Web scraping and API calls
- Data processing and transformation
- External system integration
- Custom business logic

---

## Implementation Guidelines

### Thread Safety
All core interfaces must be thread-safe:
- Use locks for shared state
- Avoid mutable class variables
- Document thread-safety guarantees

### Error Handling
Core interfaces should:
- Raise specific exceptions (not generic `Exception`)
- Include context in error messages
- Log errors for observability
- Provide remediation hints

### Observability
All operations should be tracked:
- Start/end timestamps
- Input parameters
- Output results
- Error details
- Performance metrics

### Configuration
All implementations should support:
- YAML-based configuration
- Pydantic schema validation
- Environment variable overrides
- Sensible defaults

## Related Documentation

- [Data Models](../models/) - Configuration and observability schemas
- [System Overview](../../architecture/SYSTEM_OVERVIEW.md) - How interfaces fit together
- [Documentation Index](../../INDEX.md) - All documentation
