# Task: m1-05-example-configs - Create example YAML configs for agents, stages, workflows

**Priority:** NORMAL
**Effort:** 1-2 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Create example YAML configuration files for testing and demonstration. Include simple research agent, research stage, and basic workflow that can be used in integration tests.

---

## Files to Create

- `configs/agents/simple_researcher.yaml` - Basic research agent
- `configs/stages/research_stage.yaml` - Single-agent research stage
- `configs/workflows/simple_research.yaml` - End-to-end research workflow
- `configs/tools/calculator.yaml` - Basic calculator tool config
- `configs/prompts/researcher_base.txt` - Example prompt template

---

## Acceptance Criteria

- [x] - [ ] At least 1 agent config (simple_researcher)
- [x] - [ ] At least 1 stage config (research_stage)
- [x] - [ ] At least 1 workflow config (simple_research)
- [x] - [ ] At least 1 tool config (calculator)
- [x] - [ ] At least 1 prompt template
- [x] - [ ] All configs valid against schemas (m1-04)
- [x] - [ ] Configs work together (workflow references stage, stage references agent)
- [x] - [ ] Comments explaining key fields

---

## Implementation Example

**configs/agents/simple_researcher.yaml:**
```yaml
agent:
  name: simple_researcher
  description: "Basic research agent for testing"
  version: "1.0"

  prompt:
    inline: "You are a researcher. Analyze the given topic and provide insights."

  inference:
    provider: ollama
    model: llama3.2:3b
    base_url: http://localhost:11434
    temperature: 0.7
    max_tokens: 2048

  tools:
    - Calculator

  safety:
    mode: execute
    max_tool_calls_per_execution: 5

  memory:
    enabled: false
```

---

## Success Metrics

- [x] - [ ] All example configs load successfully
- [x] - [ ] Configs pass validation
- [x] - [ ] Workflow → stage → agent references work

---

## Dependencies

- **Blocked by:** m1-04-config-schemas
- **Blocks:** m1-07-integration

---

## Notes

- Keep examples simple for Milestone 1
- Add more complex examples in later milestones
