# Code Quality Tasks - Summary

This document summarizes all code quality tasks created from the comprehensive quality control review conducted on 2026-01-27.

## Overview

**Total Tasks Created:** 28
- **P0 (Critical):** 4 tasks - Must fix before production
- **P1 (High Priority):** 12 tasks - Fix in Q1 (next 3 months)
- **P2 (Medium Priority):** 9 tasks - Fix in Q2 (months 4-6)
- **P3 (Low Priority):** 3 tasks - Nice-to-haves

## Task Breakdown by Category

### Security (6 tasks)
- cq-p0-01: Fix SSRF Vulnerability in WebScraper
- cq-p0-02: Implement Secrets Management
- cq-p0-04: SQL Injection Audit
- cq-p1-12: Implement Missing Safety Policies
- cq-p2-05: Add Content-Type Validation to WebScraper
- cq-p2-07: Enhance Environment Variable Validation

### Performance (9 tasks)
- cq-p0-03: Fix N+1 Database Query Problem
- cq-p1-02: Add HTTP Connection Pooling
- cq-p1-03: Implement Prompt Caching
- cq-p1-09: Cache Tool Registry Auto-Discovery
- cq-p1-10: Optimize Regex Compilation
- cq-p1-11: Optimize Database Session Reuse
- cq-p2-02: Add Performance Instrumentation
- cq-p2-09: Add Database Indices
- cq-p2-10: Optimize String Concatenation

### Architecture/Refactoring (5 tasks)
- cq-p1-01: Refactor LangGraphCompiler (Extract Stage Executors)
- cq-p1-07: Extract Duplicate Error Handling
- cq-p2-01: Add Configuration Versioning
- cq-p2-03: Implement LLM Response Caching
- cq-p2-04: Refactor State Management

### Code Quality (8 tasks)
- cq-p1-04: Add Comprehensive Logging
- cq-p1-05: Fix Thread Pool Cleanup
- cq-p1-06: Add Input Validation to Agents
- cq-p1-08: Add Named Constants
- cq-p2-06: Enhance Error Context in Exceptions
- cq-p2-08: Add Tool Parameter Validation
- cq-p3-01: Fix Hardcoded Confidence Score
- cq-p3-03: Integrate Observability with Safety Violations

## P0 (Critical) - Week 1

These are CRITICAL security and performance issues that must be fixed immediately.

### cq-p0-01: Fix SSRF Vulnerability in WebScraper
**Files:** `src/tools/web_scraper.py`
**Effort:** 1-2 days
**Parallelizable:** Yes (independent of other tasks)

**Why Critical:** 
- Allows attackers to access internal services (localhost, AWS metadata)
- Can lead to credential theft and internal network reconnaissance
- Major security vulnerability

**Acceptance Criteria:**
- Block localhost, private IPs, cloud metadata endpoints
- DNS rebinding protection
- 5+ security test cases

---

### cq-p0-02: Implement Secrets Management
**Files:** `src/compiler/schemas.py`, `src/compiler/config_loader.py`, `src/agents/llm_providers.py`, `src/utils/secrets.py` (new)
**Effort:** 3-5 days
**Parallelizable:** Yes (different files than SSRF)

**Why Critical:**
- API keys stored in plaintext in YAML configs
- Security breach risk
- Compliance violation

**Acceptance Criteria:**
- API keys loaded from environment variables
- Support for secret references (${env:VAR_NAME})
- All secrets redacted in logs
- Backward compatibility with deprecation warnings

---

### cq-p0-03: Fix N+1 Database Query Problem
**Files:** `src/observability/tracker.py`
**Effort:** 1-2 days
**Parallelizable:** Yes (different module)

**Why Critical:**
- 50+ unnecessary database queries per workflow
- Performance bottleneck for large workflows
- Scales poorly

**Acceptance Criteria:**
- Use SQL aggregation instead of Python loops
- Reduce queries by 80%+
- Aggregation time <50ms for 50+ executions

---

### cq-p0-04: SQL Injection Audit
**Files:** `src/observability/database.py`, `src/observability/tracker.py`
**Effort:** 1 day (audit)
**Parallelizable:** Yes (review task)

**Why Critical:**
- Potential for SQL injection via text() usage
- Could lead to database compromise

**Acceptance Criteria:**
- Audit all text() usage
- Create safe query guidelines
- Add linting rules

---

## P1 (High Priority) - Month 1

These significantly improve code quality, performance, and maintainability.

### cq-p1-01: Refactor LangGraphCompiler (Extract Stage Executors)
**Files:** `src/compiler/langgraph_compiler.py`, `src/compiler/executors/*` (new)
**Effort:** 3-4 weeks
**Parallelizable:** No (major refactor, coordinate with team)

**Impact:**
- God class (1,218 lines) violates Single Responsibility Principle
- Hard to test, maintain, extend
- Blocks future features

**Acceptance Criteria:**
- Reduce to <500 lines
- Extract executors, quality gates, synthesis
- 100% backward compatibility

---

### cq-p1-02: Add HTTP Connection Pooling
**Files:** `src/agents/llm_providers.py`
**Effort:** 1 day
**Parallelizable:** Yes

**Impact:** 50-200ms reduction per LLM call

---

### cq-p1-03: Implement Prompt Caching
**Files:** `src/agents/standard_agent.py`
**Effort:** 2 days
**Parallelizable:** Yes

**Impact:** 5-20ms per iteration, 10x savings for multi-turn

---

### cq-p1-04: Add Comprehensive Logging
**Files:** Multiple (src/core/service.py, src/observability/*)
**Effort:** 1 week
**Parallelizable:** Yes

**Impact:** Better production debugging, replaces print() statements

---

### cq-p1-05: Fix Thread Pool Cleanup
**Files:** `src/tools/executor.py`
**Effort:** 1 day
**Parallelizable:** Yes

**Impact:** Prevent thread leaks in long-running processes

---

### cq-p1-06: Add Input Validation to Agents
**Files:** `src/agents/standard_agent.py`
**Effort:** 2 days
**Parallelizable:** Yes

**Impact:** Prevent KeyError and TypeError at runtime

---

### cq-p1-07: Extract Duplicate Error Handling
**Files:** `src/utils/error_handling.py` (new), multiple files
**Effort:** 1-2 weeks
**Parallelizable:** Partial (can extract utilities first)

**Impact:** Consistent error handling, reduced duplication

---

### cq-p1-08: Add Named Constants
**Files:** Multiple (config_loader, agents, tools)
**Effort:** 2 days
**Parallelizable:** Yes

**Impact:** Better code clarity, easier to adjust limits

---

### cq-p1-09: Cache Tool Registry Auto-Discovery
**Files:** `src/tools/registry.py`
**Effort:** 1 day
**Parallelizable:** Yes

**Impact:** 100-500ms savings per agent creation

---

### cq-p1-10: Optimize Regex Compilation
**Files:** `src/agents/standard_agent.py`
**Effort:** 1 day
**Parallelizable:** Yes

**Impact:** 1-5ms per LLM response parse

---

### cq-p1-11: Optimize Database Session Reuse
**Files:** `src/observability/tracker.py`
**Effort:** 1 day
**Parallelizable:** Yes

**Impact:** Reduce connection overhead 5-50ms per operation

---

### cq-p1-12: Implement Missing Safety Policies
**Files:** `src/safety/blast_radius.py`, `src/safety/secret_detection.py`, `src/safety/rate_limiter.py` (new)
**Effort:** 1 week
**Parallelizable:** Yes

**Impact:** Production-ready safety system

---

## P2 (Medium Priority) - Months 2-3

### cq-p2-01: Add Configuration Versioning
**Files:** `src/compiler/schemas.py`, `src/utils/config_migrations.py` (new)
**Effort:** 1 week
**Parallelizable:** Yes

---

### cq-p2-02: Add Performance Instrumentation
**Files:** `src/observability/performance.py` (new)
**Effort:** 1 week
**Parallelizable:** Yes

---

### cq-p2-03: Implement LLM Response Caching
**Files:** `src/cache/llm_cache.py` (new), `src/agents/llm_providers.py`
**Effort:** 2 weeks
**Parallelizable:** Yes

**Impact:** Major cost savings, faster development iteration

---

### cq-p2-04: Refactor State Management
**Files:** `src/compiler/state.py` (new), `src/compiler/langgraph_compiler.py`
**Effort:** 1 week
**Parallelizable:** After cq-p1-01 completes

---

### cq-p2-05: Add Content-Type Validation to WebScraper
**Files:** `src/tools/web_scraper.py`
**Effort:** 1 day
**Parallelizable:** Yes

---

### cq-p2-06: Enhance Error Context in Exceptions
**Files:** Multiple
**Effort:** 1-2 weeks (incremental)
**Parallelizable:** Yes

---

### cq-p2-07: Enhance Environment Variable Validation
**Files:** `src/compiler/config_loader.py`
**Effort:** 2 days
**Parallelizable:** Yes

---

### cq-p2-08: Add Tool Parameter Validation
**Files:** `src/tools/base.py`
**Effort:** 3 days
**Parallelizable:** Yes

---

### cq-p2-09: Add Database Indices
**Files:** `src/observability/migrations.py`
**Effort:** 1 day
**Parallelizable:** Yes

---

### cq-p2-10: Optimize String Concatenation
**Files:** `src/agents/standard_agent.py`
**Effort:** 1 day
**Parallelizable:** Yes

---

## P3 (Low Priority) - Backlog

### cq-p3-01: Fix Hardcoded Confidence Score
**Files:** `src/compiler/langgraph_compiler.py`
**Effort:** 1-2 days

---

### cq-p3-02: Implement Config-Based Tool Loading
**Files:** `src/agents/standard_agent.py`
**Effort:** 1 week

---

### cq-p3-03: Integrate Observability with Safety Violations
**Files:** `src/core/service.py`
**Effort:** 2-3 days

---

## Parallelization Strategy

### Week 1 (4 agents working in parallel)
- Agent 1: cq-p0-01 (SSRF fix)
- Agent 2: cq-p0-02 (Secrets management)
- Agent 3: cq-p0-03 (N+1 queries)
- Agent 4: cq-p0-04 (SQL injection audit)

### Week 2-4 (Multiple agents)
Can work in parallel since they touch different files:
- cq-p1-02 (llm_providers.py)
- cq-p1-03 (standard_agent.py - prompt caching)
- cq-p1-04 (logging - multiple files)
- cq-p1-05 (executor.py)
- cq-p1-06 (standard_agent.py - validation)
- cq-p1-08 (constants - multiple files)
- cq-p1-09 (registry.py)
- cq-p1-10 (standard_agent.py - regex)
- cq-p1-11 (tracker.py)
- cq-p1-12 (safety/* new files)

### Month 2+ (Coordinate around refactor)
- cq-p1-01 (LangGraph refactor) - needs coordination
- Other P2 tasks can proceed in parallel

---

## Dependencies and Blockers

**No Blockers:**
- All P0 tasks can run in parallel
- Most P1 tasks can run in parallel

**Coordination Needed:**
- cq-p1-01 (LangGraph refactor) - large change, coordinate with team
- cq-p2-04 (State management) - depends on cq-p1-01 completing

**Sequential:**
- cq-p1-07 (Error handling) - Extract utilities first, then refactor usages

---

## Success Metrics

### Week 1 Completion
- [ ] All 4 P0 tasks completed
- [ ] SSRF vulnerability patched
- [ ] Secrets moved to env vars
- [ ] Database queries optimized

### Month 1 Completion
- [ ] 12 P1 tasks completed (or in progress)
- [ ] LangGraph refactor done
- [ ] Performance improved 40-60%
- [ ] Code quality score: A- (90/100)

### Quarter 1 Completion
- [ ] All P0/P1 tasks done
- [ ] Most P2 tasks done
- [ ] Security posture: HIGH (8/10)
- [ ] Technical debt reduced 30%

---

## Notes

- Tasks prefixed with 'cq' for code quality
- All tasks searchable via `.claude-coord/claude-coord.sh task-search <keyword>`
- Detailed specs available for complex tasks via `task-spec <task-id>`
- Use `task-claim` to work on tasks in multi-agent mode

**Generated:** 2026-01-27 by quality control review
**Review Sources:** Code review, security audit, technical debt assessment, architecture review, performance analysis
