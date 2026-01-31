# Contributing Guide

Thank you for your interest in contributing to the Meta-Autonomous Agent Framework! This guide will help you get started.

---

## Table of Contents

1. [Code of Conduct](#code-of-conduct)
2. [Quick Start for Contributors](#quick-start-for-contributors)
3. [Types of Contributions](#types-of-contributions)
4. [Development Setup](#development-setup)
5. [Code Standards](#code-standards)
6. [Testing Requirements](#testing-requirements)
7. [Pull Request Process](#pull-request-process)
8. [Documentation](#documentation)
9. [Issue Guidelines](#issue-guidelines)
10. [Getting Help](#getting-help)

---

## Code of Conduct

### Our Pledge

We pledge to make participation in this project a harassment-free experience for everyone, regardless of age, body size, disability, ethnicity, gender identity, level of experience, nationality, personal appearance, race, religion, or sexual identity and orientation.

### Our Standards

**Positive behaviors:**
- Using welcoming and inclusive language
- Being respectful of differing viewpoints
- Gracefully accepting constructive criticism
- Focusing on what is best for the community
- Showing empathy towards other community members

**Unacceptable behaviors:**
- Harassment, trolling, or derogatory comments
- Publishing others' private information
- Professional or personal attacks
- Other conduct that would be inappropriate in a professional setting

---

## Quick Start for Contributors

### 1. Fork and Clone

```bash
# Fork the repository on GitHub
# Then clone your fork
git clone https://github.com/YOUR_USERNAME/meta-autonomous-framework.git
cd meta-autonomous-framework
```

### 2. Create Branch

```bash
# Create a feature branch
git checkout -b feature/your-feature-name

# Or a bugfix branch
git checkout -b fix/issue-123
```

### 3. Make Changes

```bash
# Make your changes
# Run tests
pytest

# Check code style
black src/ tests/
flake8 src/ tests/
```

### 4. Commit and Push

```bash
# Commit with descriptive message
git commit -m "Add feature: your feature description"

# Push to your fork
git push origin feature/your-feature-name
```

### 5. Create Pull Request

- Go to GitHub and create a Pull Request
- Fill out the PR template
- Wait for review

---

## Types of Contributions

### 🐛 Bug Reports

Found a bug? Please create an issue with:
- Clear description of the bug
- Steps to reproduce
- Expected vs. actual behavior
- Environment details (OS, Python version)
- Relevant logs or error messages

**Template:**
```markdown
**Bug Description:**
Clear description of what's wrong

**Steps to Reproduce:**
1. Step one
2. Step two
3. See error

**Expected Behavior:**
What should happen

**Actual Behavior:**
What actually happens

**Environment:**
- OS: Ubuntu 22.04
- Python: 3.11
- Framework version: 1.0.0
```

### ✨ Feature Requests

Have an idea? Please create an issue with:
- Clear description of the feature
- Use case / motivation
- Proposed implementation (if any)
- Alternatives considered

**Template:**
```markdown
**Feature Description:**
Clear description of the feature

**Use Case:**
Why is this needed?

**Proposed Solution:**
How could this work?

**Alternatives:**
Other approaches considered
```

### 📝 Documentation

Documentation improvements are always welcome:
- Fix typos or clarify confusing sections
- Add examples or tutorials
- Improve API documentation
- Write guides for common tasks

### 🔧 Code Contributions

Code contributions include:
- Bug fixes
- New features
- Performance improvements
- Refactoring
- Test coverage improvements

---

## Development Setup

### Prerequisites

- **Python 3.11+** (required)
- **Git** (required)
- **PostgreSQL** (optional, for observability)
- **Ollama** (optional, for local LLMs)

### Installation

1. **Clone your fork:**
```bash
git clone https://github.com/YOUR_USERNAME/meta-autonomous-framework.git
cd meta-autonomous-framework
```

2. **Create virtual environment:**
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```

3. **Install in development mode:**
```bash
pip install -e ".[dev]"
```

This installs:
- Core dependencies
- Development tools (pytest, black, flake8)
- Documentation tools (sphinx, mkdocs)

4. **Install pre-commit hooks (optional):**
```bash
pip install pre-commit
pre-commit install
```

### Verify Installation

```bash
# Run tests
pytest

# Check import works
python -c "from src.agents.standard_agent import StandardAgent; print('OK')"
```

---

## Code Standards

### Python Style

We follow **PEP 8** with a few modifications:

- **Line length:** 100 characters (not 79)
- **String quotes:** Double quotes preferred
- **Imports:** Grouped and sorted

### Code Formatting

We use **Black** for automatic formatting:

```bash
# Format all code
black src/ tests/

# Check formatting
black --check src/ tests/
```

**Configuration:** `pyproject.toml`
```toml
[tool.black]
line-length = 100
target-version = ['py311']
```

### Linting

We use **flake8** for linting:

```bash
# Lint code
flake8 src/ tests/

# With specific rules
flake8 --max-line-length=100 src/
```

**Configuration:** `.flake8`
```ini
[flake8]
max-line-length = 100
exclude = .git,__pycache__,venv
ignore = E203,W503
```

### Type Hints

Use type hints for all public functions:

```python
from typing import Dict, List, Optional, Any

def process_data(
    input_data: Dict[str, Any],
    config: Optional[Dict[str, str]] = None
) -> List[str]:
    """Process input data and return results.

    Args:
        input_data: Input data dictionary
        config: Optional configuration

    Returns:
        List of processed results
    """
    # Implementation
    return results
```

### Docstrings

Use **Google-style** docstrings:

```python
def calculate_score(
    inputs: List[float],
    weights: Optional[List[float]] = None
) -> float:
    """Calculate weighted score from inputs.

    Computes a weighted sum of input values. If weights are not
    provided, uses equal weights for all inputs.

    Args:
        inputs: List of input values
        weights: Optional list of weights (must match inputs length)

    Returns:
        Calculated weighted score

    Raises:
        ValueError: If weights length doesn't match inputs length

    Example:
        >>> calculate_score([1, 2, 3], [0.5, 0.3, 0.2])
        1.8
    """
    if weights is None:
        weights = [1.0] * len(inputs)

    if len(weights) != len(inputs):
        raise ValueError("Weights length must match inputs length")

    return sum(i * w for i, w in zip(inputs, weights))
```

### Naming Conventions

| Type | Convention | Example |
|------|------------|---------|
| Classes | PascalCase | `StandardAgent`, `LLMCache` |
| Functions | snake_case | `execute_workflow`, `parse_config` |
| Constants | UPPER_SNAKE_CASE | `MAX_RETRIES`, `DEFAULT_TIMEOUT` |
| Private methods | _leading_underscore | `_validate_input`, `_process_data` |
| Modules | snake_case | `config_loader.py`, `llm_providers.py` |

---

## Testing Requirements

### Test Coverage

- **All new code** must have tests
- **Minimum coverage:** 80% overall
- **Critical paths:** 90%+ coverage

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src tests/

# Run specific test file
pytest tests/test_agents/test_standard_agent.py -v
```

### Writing Tests

**Structure:**
```python
def test_feature_description():
    """Test that feature works correctly."""
    # Arrange
    setup_data = create_test_data()

    # Act
    result = function_under_test(setup_data)

    # Assert
    assert result.success is True
    assert result.value == expected_value
```

**Fixtures:**
```python
import pytest

@pytest.fixture
def sample_config():
    """Provide sample configuration for tests."""
    return {
        "name": "test",
        "version": "1.0"
    }

def test_with_fixture(sample_config):
    """Test using fixture."""
    assert sample_config["name"] == "test"
```

### Test Types Required

1. **Unit tests** - Test individual functions/classes
2. **Integration tests** - Test component interactions
3. **Edge cases** - Test boundary conditions
4. **Error handling** - Test error paths

---

## Pull Request Process

### Before Creating PR

**Checklist:**
- [ ] Code follows style guidelines
- [ ] All tests pass (`pytest`)
- [ ] New tests added for new functionality
- [ ] Documentation updated
- [ ] Code formatted (`black`)
- [ ] Linting passes (`flake8`)
- [ ] Commit messages are descriptive

### Creating the PR

1. **Push your branch:**
```bash
git push origin feature/your-feature-name
```

2. **Create PR on GitHub:**
- Go to the repository
- Click "New Pull Request"
- Select your branch
- Fill out the template

3. **PR Template:**
```markdown
## Description
Clear description of what this PR does

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## How Has This Been Tested?
Describe the tests you ran

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Code commented where needed
- [ ] Documentation updated
- [ ] Tests added
- [ ] All tests pass
```

### PR Review Process

1. **Automated checks** run (tests, linting)
2. **Maintainer reviews** code
3. **Feedback provided** (if needed)
4. **You address feedback**
5. **Maintainer approves and merges**

### Addressing Feedback

```bash
# Make requested changes
# Commit changes
git add .
git commit -m "Address review feedback: clarify error handling"

# Push to same branch
git push origin feature/your-feature-name
```

The PR will automatically update!

---

## Documentation

### When to Update Docs

Update documentation when:
- Adding new features
- Changing existing behavior
- Adding new configuration options
- Fixing bugs that affect usage
- Adding examples

### Documentation Types

**1. Code Documentation (Docstrings)**
- All public functions/classes
- Google-style format
- Include examples

**2. User Guides (`/docs`)**
- Feature guides
- Tutorials
- Best practices

**3. API Reference**
- Auto-generated from docstrings
- Keep docstrings up to date

**4. README Updates**
- New features in quick start
- Updated status
- New examples

### Documentation Style

- **Clear and concise**
- **Include examples**
- **Use active voice**
- **Avoid jargon** (or explain it)

### Emoji Usage Policy

**When to use emojis:**
- ✅ **README files** - Emojis enhance readability and visual appeal
- ✅ **User-facing guides and tutorials** - Makes content more engaging
- ✅ **QUICK_START.md** - Helps users navigate getting started
- ✅ **Status indicators** - Quick visual feedback (✓, ✗, ⚠️)

**When NOT to use emojis:**
- ❌ **API documentation** - Keep formal and professional
- ❌ **Technical specifications** - Clarity over aesthetics
- ❌ **Code comments** - Use clear text instead
- ❌ **Error messages** - Text-only for parsing/searching
- ❌ **Configuration files** - Avoid potential encoding issues

**Approved emojis for status indicators:**

| Emoji | Usage | Example |
|-------|-------|---------|
| ✅ ✓ | Success, completed, allowed | ✅ Tests passing |
| ❌ ✗ | Error, failed, blocked | ❌ Action blocked |
| ⚠️ | Warning, caution | ⚠️ Deprecated feature |
| ℹ️ | Information, note | ℹ️ See documentation |
| ⏸ | Paused, pending | ⏸ Planned feature |
| 🔥 | Critical, important | 🔥 Security issue |
| 🚀 | New feature, deployment | 🚀 Feature released |
| 🐛 | Bug | 🐛 Fixed authentication bug |
| 📝 | Documentation | 📝 Updated API docs |

**Examples:**

**Good (README.md):**
```markdown
## Quick Start

✅ **Supported:** Python 3.8+
❌ **Not Supported:** Python 3.7

### Features

🚀 Multi-agent collaboration
🔒 Built-in safety policies
📊 Observability and monitoring
```

**Bad (API_REFERENCE.md):**
```markdown
## ActionPolicyEngine

✅ The ActionPolicyEngine validates actions... ❌ WRONG!
```

**Correct (API_REFERENCE.md):**
```markdown
## ActionPolicyEngine

The ActionPolicyEngine validates actions against registered policies.
```

**Rule of thumb:** If the document is for developers reading code or API specs, avoid emojis. If it's for users getting started or learning the framework, emojis are welcome.

### File Naming Convention

**Main documentation (`docs/*.md`):**
- ✅ **UPPERCASE.md** - All primary documentation files
- Examples: `README.md`, `API_REFERENCE.md`, `CONFIGURATION.md`, `TESTING.md`
- Rationale: Easy to distinguish important docs, consistent with GitHub conventions

**Subdirectory documentation (`docs/*/`):**
- ✅ **UPPERCASE.md** - Major documents (API reference, configuration, guides)
- ✅ **README.md** - Directory index or overview (GitHub convention)
- ✅ **lowercase_with_underscores.md** - Supporting documents, examples, notes

**Examples:**

```
docs/
├── API_REFERENCE.md                    # ✅ Main API doc
├── CONFIGURATION.md                    # ✅ Main config doc
├── TESTING.md                          # ✅ Main testing doc
├── security/
│   ├── README.md                       # ✅ Security overview
│   ├── M4_SAFETY_SYSTEM.md            # ✅ Major doc
│   ├── SAFETY_EXAMPLES.md             # ✅ Major doc
│   └── threat_model.md                # ✅ Supporting doc
└── features/
    ├── README.md                       # ✅ Features index
    ├── multi_agent_collab.md          # ✅ Feature detail
    └── observability.md               # ✅ Feature detail
```

**When to use UPPERCASE:**
- Primary framework documentation (API, config, testing, architecture)
- Major feature guides (M4 Safety, Multi-Agent, Observability)
- Top-level docs that users will frequently reference

**When to use lowercase:**
- Supporting documentation within subdirectories
- Examples, tutorials, how-tos
- Archive documents, changelogs, meeting notes
- Internal development docs

**Never use:**
- ❌ **Title-Case.md** or **Title_Case.md** - Inconsistent, hard to predict
- ❌ **mixedCase.md** or **camelCase.md** - Violates Python community conventions
- ❌ **Spaces In Names.md** - Breaks command-line tools and URLs

**Rule of thumb:** If it's a major doc users will search for, use UPPERCASE.md. If it's supporting content, use lowercase_with_underscores.md.

---

## Issue Guidelines

### Creating Good Issues

**Good Issue:**
```markdown
**Title:** Agent fails with timeout error when using OpenAI

**Description:**
When executing a workflow with OpenAI provider, the agent
crashes with a timeout error after 30 seconds.

**Steps to Reproduce:**
1. Configure agent with OpenAI provider
2. Set timeout to 30 seconds
3. Run workflow with long prompt
4. Observe timeout error

**Expected:** Agent should handle timeout gracefully
**Actual:** Agent crashes with stack trace

**Environment:**
- OS: Ubuntu 22.04
- Python: 3.11.2
- Framework: v1.0.0

**Logs:**
```
Traceback (most recent call last):
  ...
```

**Bad Issue:**
```markdown
**Title:** It doesn't work

**Description:** Help!
```

### Issue Labels

| Label | Description |
|-------|-------------|
| `bug` | Something isn't working |
| `enhancement` | New feature or request |
| `documentation` | Improvements to docs |
| `good first issue` | Good for newcomers |
| `help wanted` | Extra attention needed |
| `question` | Further information requested |

---

## Getting Help

### Resources

- **Documentation:** `/docs` directory
- **Examples:** `/examples` directory
- **Tests:** `/tests` directory (working examples)

### Communication Channels

- **GitHub Issues:** Bug reports, feature requests
- **GitHub Discussions:** Questions, ideas
- **Pull Requests:** Code review, technical discussion

### Response Times

- **Issues:** Typically reviewed within 1-2 business days
- **PRs:** Typically reviewed within 2-3 business days
- **Security issues:** Responded to within 24 hours

---

## Common Contribution Scenarios

### Scenario 1: Fix a Typo

**Fastest path:**
1. Fork repository
2. Edit file directly on GitHub
3. Create PR with clear title: "Fix typo in QUICKSTART.md"
4. Done!

### Scenario 2: Add a New Tool

**Steps:**
1. Create tool class in `src/tools/your_tool.py`
2. Inherit from `BaseTool`
3. Implement required methods
4. Add tests in `tests/test_tools/test_your_tool.py`
5. Update tool documentation
6. Create PR

**Example:**
```python
from src.tools.base import BaseTool, ToolResult

class MyTool(BaseTool):
    @property
    def name(self) -> str:
        return "my_tool"

    @property
    def description(self) -> str:
        return "My custom tool"

    def execute(self, **kwargs) -> ToolResult:
        # Implementation
        return ToolResult(success=True, result="done")
```

### Scenario 3: Add a New Feature

**Steps:**
1. Create issue describing feature
2. Wait for approval/feedback
3. Create feature branch
4. Implement feature with tests
5. Update documentation
6. Create PR referencing issue

### Scenario 4: Report a Bug

**Steps:**
1. Check if issue already exists
2. Create new issue with details
3. Include reproduction steps
4. Add environment information
5. Optionally submit fix via PR

---

## Development Workflow

### Typical Development Cycle

```bash
# 1. Create feature branch
git checkout -b feature/new-feature

# 2. Make changes
# Edit files...

# 3. Run tests frequently
pytest tests/test_relevant_module.py -v

# 4. Format code
black src/ tests/

# 5. Check linting
flake8 src/ tests/

# 6. Run full test suite
pytest --cov=src tests/

# 7. Commit changes
git add .
git commit -m "Add new feature: description"

# 8. Push and create PR
git push origin feature/new-feature
```

### Working with Multiple Commits

```bash
# Make several small commits
git commit -m "Add base implementation"
git commit -m "Add tests"
git commit -m "Update documentation"

# Squash before PR (optional)
git rebase -i HEAD~3

# Or maintainer will squash on merge
```

---

## Advanced Topics

### Adding Dependencies

**Guidelines:**
- Keep dependencies minimal
- Only add well-maintained packages
- Check license compatibility
- Update `setup.py` and `requirements.txt`

**Process:**
1. Add to `setup.py` under `install_requires`
2. Update `requirements.txt` with version
3. Document in PR why dependency is needed

### Breaking Changes

**If your change breaks existing API:**
1. Discuss in issue first
2. Document migration path
3. Consider deprecation period
4. Update CHANGELOG.md
5. Increment major version

### Performance Improvements

**Guidelines:**
- Benchmark before and after
- Include benchmark results in PR
- Use `pytest-benchmark` for tests
- Document performance gains

**Example:**
```python
def test_performance(benchmark):
    """Benchmark function performance."""
    result = benchmark(expensive_function, arg1, arg2)
    assert result is not None
```

---

## Recognition

### Contributors

All contributors are recognized in:
- `CONTRIBUTORS.md` file
- Release notes
- Project README

### Becoming a Maintainer

Regular contributors may be invited to become maintainers.

**Criteria:**
- Consistent high-quality contributions
- Good understanding of codebase
- Helpful in reviews and discussions
- Follows project guidelines

---

## Thank You!

Thank you for contributing to the Meta-Autonomous Agent Framework. Every contribution, no matter how small, helps make this project better for everyone.

**Questions?** Open an issue or discussion on GitHub!

Happy coding! 🚀
