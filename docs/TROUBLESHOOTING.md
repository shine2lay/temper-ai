# Troubleshooting Guide

Solutions to common issues when using the Meta-Autonomous Agent Framework.

---

## Quick Diagnostics

```bash
# Check Python version
python --version  # Should be 3.11+

# Check installation
python -c "from src.agents.standard_agent import StandardAgent; print('OK')"

# Run tests
pytest tests/test_agents/ -v

# Check Ollama
curl http://localhost:11434/api/tags
```

---

## Installation Issues

### ImportError: No module named 'src'

**Solution:**
```bash
pip install -e .
```

### Package not found

**Solution:**
```bash
pip install -e ".[dev]"
```

---

## Configuration Issues

### ValidationError: field required

**Check:** All required fields present
**Solution:** See CONFIGURATION.md

### YAML syntax error

**Solution:** Check indentation, use spaces not tabs

---

## LLM Provider Issues

### Ollama connection refused

**Solution:**
```bash
ollama serve
```

### OpenAI API key not found

**Solution:**
```bash
export OPENAI_API_KEY=sk-...
```

### Model not found

**Solution:**
```bash
ollama pull llama3.2:3b
```

---

## Execution Issues

### Agent timeout

**Increase timeout:**
```yaml
inference:
  timeout_seconds: 120
```

### Tool execution fails

**Check:** Tool registered correctly
**Check:** Parameters valid

### Out of memory

**Solution:** Use smaller model or increase RAM

---

## Performance Issues

### Slow execution

**Solutions:**
- Use local LLM (Ollama)
- Enable caching
- Use parallel execution

### High costs

**Solutions:**
- Use cheaper models
- Enable caching
- Limit max_tokens

---

## Database Issues

### Connection error

**Check:** Database running
**Check:** Connection string correct

### Migration errors

**Solution:**
```bash
alembic upgrade head
```

---

## Getting Help

- **Documentation:** `/docs`
- **Examples:** `/examples`
- **Issues:** GitHub Issues
- **Tests:** Working examples in `/tests`

---

For detailed guides, see:
- [QUICK_START.md](./QUICK_START.md)
- [CONFIGURATION.md](./CONFIGURATION.md)
- [TESTING.md](./TESTING.md)
