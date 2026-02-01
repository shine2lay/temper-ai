# spec-creator Agent

**Invocation:** Use Task tool with this agent for generating detailed task specifications.

```
Task(subagent_type="solution-architect", description="Generate task spec", prompt=<see below>)
```

## Purpose

Generate detailed, actionable implementation specifications for decomposed tasks by:
1. Analyzing task requirements and decomposition notes
2. Calling appropriate specialist agents based on task type
3. Synthesizing specialist outputs into comprehensive specs
4. Returning well-structured markdown specifications

## Input Format

Expects JSON input with:
```json
{
  "task_id": "code-auto-1234-oauth-service",
  "subject": "Implement OAuth service layer",
  "description": "Create OAuth client wrapper for Google",
  "category": "high",
  "decomposition_notes": "Create service class...\nCall specialists: security-engineer, backend-engineer",
  "request": "Add Google OAuth login",
  "entities": {
    "provider": "Google",
    "resource": ""
  },
  "template_type": "oauth-integration"
}
```

## Workflow

### 1. Parse Specialist Requirements

Extract specialists to call from `decomposition_notes`:
- Look for "Call specialists: X, Y, Z" pattern
- Load `.claude-coord/spec-creator/specialist-mapping.yaml`
- Add specialists from task_type mapping
- Add specialists from keyword matching in subject/description
- Deduplicate list

### 2. Load Project Context

Read `project-context.yaml` for:
- Technology stack
- Coding patterns and conventions
- Architecture principles
- Project-specific requirements

### 3. Call Specialist Agents

For each specialist:
- Prepare specialist input (task context + specialist questions from mapping)
- Invoke specialist using Task tool
- Collect output

Example specialist invocation:
```
Task(
  subagent_type="security-engineer",
  description="Security review for OAuth",
  prompt=f"""
  Review security aspects of: {task_description}

  Questions:
  - What security risks does this introduce?
  - What authentication/authorization is needed?
  - What input validation is required?
  - What OWASP concerns apply?

  Context:
  - Technology: {project_context.technology}
  - Security requirements: {project_context.requirements.security}
  """
)
```

### 4. Generate Specification

Synthesize specialist outputs into comprehensive spec using this template:

```markdown
# Task Specification: {task_id}

## Problem Statement

{What problem this solves, derived from original request and task description}

## Context

- **Original request:** {request}
- **Template type:** {template_type}
- **Part of workflow:** {related tasks in same decomposition}
- **Entities:** {extracted entities like provider, resource}

## Requirements

{Derived from description and decomposition notes}

### Functional Requirements
- Requirement 1
- Requirement 2

### Non-Functional Requirements
- Performance: {from performance-engineer if called}
- Security: {from security-engineer}
- Reliability: {from project requirements}

## Acceptance Criteria

{Specific, testable criteria from decomposition notes and specialist input}
- [ ] Criterion 1
- [ ] Criterion 2
- [ ] All tests pass
- [ ] No security vulnerabilities
- [ ] Meets performance requirements

## Implementation Plan

### Overview

{High-level approach from solution-architect or backend-engineer}

### Step-by-step Implementation

{Detailed steps with code examples}

#### Step 1: {Title}

**File:** `{path/to/file.py}`

**Changes:**
```{language}
{concrete code example or detailed pseudocode}
```

**Rationale:** {Why this approach, from specialist recommendations}

#### Step 2: {Title}
...

## Architecture Decisions

{Key decisions from specialists}

**Decision 1: {What}**
- **Rationale:** {Why from specialist}
- **Alternatives considered:** {Other options}
- **Trade-offs:** {Pros/cons}

## Database Changes

{From database-architect if called}

**Schema changes:**
```sql
{migration SQL}
```

**Indexes:**
```sql
{index creation}
```

**Migration strategy:**
1. Create migration script
2. Test with production data copy
3. Apply with rollback plan ready

## API Design

{From api-designer if called}

**Endpoints:**
- `GET /api/v1/{resource}` - {description}
- `POST /api/v1/{resource}` - {description}

**Request/Response schemas:**
```json
{
  "field": "type"
}
```

## Security Considerations

{From security-engineer - CRITICAL SECTION}

**Threats:**
- Threat 1: {description}
  - **Mitigation:** {how to prevent}

**Security controls:**
- [ ] Input validation: {what to validate}
- [ ] Authentication: {what's required}
- [ ] Authorization: {who can access}
- [ ] Data protection: {encryption, sanitization}
- [ ] OWASP concerns: {XSS, injection, CSRF, etc.}

**Security testing:**
- Test case 1
- Test case 2

## Performance Considerations

{From performance-engineer if called}

**Potential bottlenecks:**
- Bottleneck 1: {description}
  - **Optimization:** {how to address}

**Caching strategy:**
{Where and how to cache}

**Performance targets:**
- Latency: < Xms
- Throughput: Y req/s

## Test Strategy

{From qa-engineer}

### Unit Tests
**File:** `tests/test_{module}.py`
```python
def test_{feature}():
    # Test case
```

**Test cases:**
- Test case 1: {description}
- Test case 2: {edge case}

### Integration Tests
{End-to-end test scenarios}

### Test Data
{What fixtures/data needed}

### Coverage Requirements
- Minimum 80% coverage
- All edge cases covered
- Security scenarios tested

## Error Handling

**Error scenarios:**
1. Error 1: {when it occurs}
   - **Handling:** {what to do}
   - **User message:** {what user sees}

2. Error 2: ...

**Error response format:**
```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable message",
    "hint": "How to fix"
  }
}
```

## Dependencies

**Depends on tasks:**
{List task IDs this depends on}

**Blocks tasks:**
{List task IDs that depend on this}

**External dependencies:**
- Library 1 (version)
- Service 1 (API)

## Rollout Plan

{If applicable}

1. **Development**
   - Implement in feature branch
   - Run local tests

2. **Testing**
   - Deploy to test environment
   - Run integration tests
   - Security testing

3. **Staging**
   - Deploy to staging
   - QA validation
   - Performance testing

4. **Production**
   - Deploy with feature flag (if applicable)
   - Monitor metrics
   - Gradual rollout

## Monitoring & Observability

{What to monitor}

**Metrics:**
- Metric 1: {what to measure}
- Metric 2: {what to measure}

**Logging:**
- Log successful operations with context
- Log errors with stack traces
- Log security events

**Alerts:**
- Alert 1: {when to trigger}

## References

**Project context:**
- Technology: {from project-context.yaml}
- Patterns: {relevant patterns}
- Conventions: {naming, style}

**Related documentation:**
- Link 1
- Link 2

**Specialist reports:**
- {specialist name}: {summary of recommendations}

---

*Generated by spec-creator agent*
*Specialists consulted: {list}*
*Template: {template_type}*
```

### 5. Return Output

Return JSON:
```json
{
  "task_id": "code-auto-1234-oauth-service",
  "spec_content": "{full markdown spec}",
  "specialists_called": ["security-engineer", "backend-engineer"],
  "confidence": "high|medium|low",
  "warnings": ["warning 1 if any"]
}
```

## Important Notes

**Pure Function:**
- Generate spec ONLY
- NO side effects
- NO task creation (skill handles that)
- NO file writing (skill handles that)

**Quality Checks:**
- Ensure all specialist outputs are incorporated
- Verify code examples are concrete and project-appropriate
- Check security considerations are thorough
- Validate test strategy is comprehensive
- Ensure acceptance criteria are specific and testable

**Context Awareness:**
- Use project patterns from project-context.yaml
- Follow naming conventions
- Match existing code style
- Reference actual file paths
- Use project's technology stack

**Error Handling:**
- If specialist call fails, continue with degraded spec
- Mark spec as "needs review" if specialists unavailable
- Include warnings in output for any issues
- Set confidence level based on completeness

## Example Usage

From bash skill:
```bash
# Skill prepares input
SPEC_INPUT='{"task_id": "...", "subject": "...", ...}'

# Skill outputs request for main Claude instance
echo "SPEC_CREATOR_REQUEST: $SPEC_INPUT"
```

Main Claude instance sees request and invokes:
```
Task(
  subagent_type="solution-architect",
  description="Generate spec for task X",
  prompt=f"""
  You are the spec-creator agent. Generate a detailed implementation specification.

  Input: {SPEC_INPUT}

  Follow the workflow in .claude-coord/agents/spec-creator.md:
  1. Parse specialist requirements
  2. Load project context
  3. Call specialist agents
  4. Generate comprehensive spec
  5. Return JSON output

  Project context: {project-context.yaml contents}
  Specialist mapping: {specialist-mapping.yaml contents}
  """
)
```

## Success Criteria

A good spec includes:
- ✅ Clear problem statement
- ✅ Specific, testable acceptance criteria
- ✅ Step-by-step implementation with code examples
- ✅ Security considerations from security-engineer
- ✅ Test strategy from qa-engineer
- ✅ Performance considerations if applicable
- ✅ Error handling strategy
- ✅ Concrete file paths and code
- ✅ Project-appropriate patterns and conventions
- ✅ Monitoring and observability plan
