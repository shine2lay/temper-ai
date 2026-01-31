# Example Guides

Comprehensive guides and tutorials for using the Meta-Autonomous Framework.

## Getting Started Guides

### [E2E YAML Workflow Guide](./E2E_YAML_WORKFLOW_GUIDE.md)
**Purpose:** Complete guide to creating workflows using YAML configuration

**Topics Covered:**
- Workflow structure and syntax
- Stage definitions
- Agent configuration
- Tool integration
- Error handling
- Testing workflows

**Best For:** First-time users learning the framework

**Length:** 619 lines, comprehensive

---

### [Multi-Agent Collaboration Examples](./multi_agent_collaboration_examples.md)
**Purpose:** Examples of M3 multi-agent collaboration features

**Topics Covered:**
- Parallel agent execution
- Collaboration strategies (voting, consensus, debate)
- Convergence detection
- Example workflows explained

**Best For:** Learning multi-agent coordination

**Length:** 235 lines, example-focused

---

## Configuration Guides

### [M3 YAML Configs Guide](./M3_YAML_CONFIGS_GUIDE.md)
**Purpose:** In-depth guide to M3 YAML configuration options

**Topics Covered:**
- Multi-agent stage configuration
- Collaboration strategy settings
- Parallel execution options
- Quality gates and thresholds
- Advanced configuration patterns

**Best For:** Advanced users configuring complex workflows

**Length:** 791 lines, comprehensive reference

---

## Analysis and Debugging

### [LLM Debate Trace Analysis](./LLM_DEBATE_TRACE_ANALYSIS.md)
**Purpose:** Analyzing debate traces and understanding agent interactions

**Topics Covered:**
- Reading debate execution traces
- Understanding convergence metrics
- Analyzing position evolution
- Performance insights
- Debugging collaboration issues

**Best For:** Understanding and debugging multi-agent debates

**Length:** 521 lines, analytical

---

### [M3 Demo Enhancements](./M3_DEMO_ENHANCEMENTS.md)
**Purpose:** Enhancements and improvements for M3 demos

**Topics Covered:**
- Demo script improvements
- Visualization enhancements
- Output formatting
- Performance optimizations
- Testing strategies

**Best For:** Contributors improving demos and examples

**Length:** 294 lines, technical

---

## Quick Reference

### By Use Case

**I want to...**

- **Learn the basics**: Start with [E2E YAML Workflow Guide](./E2E_YAML_WORKFLOW_GUIDE.md)
- **Use multi-agent collaboration**: Read [Multi-Agent Collaboration Examples](./multi_agent_collaboration_examples.md)
- **Configure advanced M3 features**: See [M3 YAML Configs Guide](./M3_YAML_CONFIGS_GUIDE.md)
- **Debug a debate workflow**: Check [LLM Debate Trace Analysis](./LLM_DEBATE_TRACE_ANALYSIS.md)
- **Improve demo scripts**: Review [M3 Demo Enhancements](./M3_DEMO_ENHANCEMENTS.md)

### By Experience Level

**Beginner:**
1. [E2E YAML Workflow Guide](./E2E_YAML_WORKFLOW_GUIDE.md) - Learn workflow basics
2. [Multi-Agent Collaboration Examples](./multi_agent_collaboration_examples.md) - See real examples

**Intermediate:**
1. [M3 YAML Configs Guide](./M3_YAML_CONFIGS_GUIDE.md) - Advanced configuration
2. [LLM Debate Trace Analysis](./LLM_DEBATE_TRACE_ANALYSIS.md) - Understand execution

**Advanced:**
1. [M3 Demo Enhancements](./M3_DEMO_ENHANCEMENTS.md) - Contribute improvements
2. All guides - Reference as needed

---

## Related Documentation

- [Examples Directory](../README.md) - Example scripts and workflows
- [Features Documentation](../../docs/features/) - Feature-specific guides
- [Interfaces Documentation](../../docs/interfaces/) - API reference
- [Milestone Reports](../../docs/milestones/) - Feature completion details

---

## Contributing Examples

### Adding New Examples
1. Create workflow config in `configs/workflows/`
2. Add example script in `examples/`
3. Document in appropriate guide or create new guide
4. Update this README with link
5. Add tests to ensure example works

### Adding New Guides
1. Write guide in Markdown
2. Place in `examples/guides/`
3. Follow structure: Purpose → Topics → Examples → Reference
4. Update this README with link and description
5. Cross-link with related guides

---

## Guide Standards

All guides should include:
- **Purpose**: What this guide teaches
- **Topics Covered**: Outline of content
- **Prerequisites**: What you need to know first
- **Examples**: Working code snippets
- **Best Practices**: Tips and recommendations
- **Troubleshooting**: Common issues and solutions
- **Related Links**: Other relevant documentation
