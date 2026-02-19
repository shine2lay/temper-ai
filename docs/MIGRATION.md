# Migration Guide

Guide for migrating between versions of the Temper AI.

---

## Version Compatibility

| From Version | To Version | Breaking Changes | Migration Time |
|--------------|------------|------------------|----------------|
| 0.x → 1.0 | 1.0.0 | Yes | 30-60 min |
| 1.0 → 1.1 | 1.1.0 | No | 5 min |
| 1.x → 2.0 | 2.0.0 | Yes (TBD) | TBD |

---

## Migrating to 1.0

### Breaking Changes

1. **Config schema updated** - New required fields
2. **LLM provider interface** - Unified response format
3. **Tool registry** - Auto-discovery off by default
4. **Observability** - New database schema

### Step 1: Update Dependencies

```bash
pip install --upgrade meta-autonomous-framework
```

### Step 2: Update Configs

**Old format (0.x):**
```yaml
agent:
  name: my_agent
  llm:
    type: ollama
    model: llama2
```

**New format (1.0):**
```yaml
agent:
  name: my_agent
  inference:
    provider: ollama
    model: llama3.2:3b
```

### Step 3: Update Code

**Old:**
```python
from temper_ai.agents import Agent
agent = Agent.from_config(config)
```

**New:**
```python
from temper_ai.agents.standard_agent import StandardAgent
agent = StandardAgent(config)
```

### Step 4: Migrate Database

```bash
alembic upgrade head
```

### Step 5: Test

```bash
pytest
```

---

## Migrating from LangChain

### Conceptual Mapping

| LangChain | Framework Equivalent |
|-----------|---------------------|
| Chain | Workflow |
| Agent | StandardAgent |
| Tool | Tool |
| LLM | LLM Provider |
| Memory | Memory (config) |

### Migration Steps

**LangChain code:**
```python
from langchain.agents import initialize_agent
from langchain.llms import Ollama

llm = Ollama(model="llama2")
agent = initialize_agent(tools, llm)
result = agent.run("query")
```

**Framework equivalent:**
```yaml
# config.yaml
agent:
  name: my_agent
  inference:
    provider: ollama
    model: llama3.2:3b
  tools:
    - Calculator
```

```python
from temper_ai.compiler.config_loader import ConfigLoader
from temper_ai.agents.standard_agent import StandardAgent

loader = ConfigLoader()
config = loader.load_agent("my_agent")
agent = StandardAgent(config)
result = agent.execute({"query": "..."})
```

---

## Migrating from AutoGen

### Mapping

| AutoGen | Framework |
|---------|-----------|
| ConversableAgent | StandardAgent |
| GroupChat | Multi-agent stage |
| UserProxyAgent | Human-in-loop |

### Example

**AutoGen:**
```python
from autogen import AssistantAgent, UserProxyAgent

assistant = AssistantAgent("assistant", llm_config=config)
user = UserProxyAgent("user")
user.initiate_chat(assistant, message="Hello")
```

**Framework:**
```yaml
workflow:
  stages:
    - name: conversation
      type: agent
      agent_ref: assistant
```

---

## Best Practices

1. **Test thoroughly** after migration
2. **Backup configs** before changes
3. **Migrate incrementally** (one component at a time)
4. **Check breaking changes** in release notes
5. **Update dependencies** together

---

## Getting Help

- **Migration issues:** GitHub Issues
- **Breaking changes:** CHANGELOG.md
- **New features:** Documentation

---

Happy migrating! 🚀
