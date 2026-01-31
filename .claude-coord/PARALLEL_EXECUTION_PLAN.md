# M3.1-M3.3 Parallel Execution Plan

**Total Duration:** 7.5 weeks
**Parallel Agents:** Up to 3-4 agents can work simultaneously

---

## Phase 1: M3.1 Code Quality (2 weeks)

### **Week 1-2: All tasks run in PARALLEL** ⚡

**Agent 1** can claim:
- `m3.1-01` - Fix type safety errors (174 → 0)
  - Priority: CRITICAL
  - No dependencies
  - 2 weeks effort

**Agent 2** can claim:
- `m3.1-02` - Fix 3 TODOs in critical paths
  - Priority: CRITICAL
  - No dependencies
  - 1 day effort

**Agent 3** can claim:
- `m3.1-03` - Fix tool registry auto-discovery
  - Priority: HIGH
  - No dependencies
  - 1-2 days effort

**Parallelization:** All 3 tasks are independent. Can run simultaneously.

---

## Phase 2: M3.2 Architecture Refactoring (3.5 weeks)

### **Week 3: Compiler Extraction Begins** (2-3 agents in parallel)

**Agent 1:**
- `m3.2-01` - Extract StateManager from compiler
  - Priority: CRITICAL
  - Can start immediately after M3.1
  - 3-4 days effort
  - **BLOCKS:** m3.2-02, m3.2-03

**Agent 2:**
- `m3.2-07` - Create observability backend abstraction
  - Priority: HIGH
  - **INDEPENDENT** - can run anytime
  - 1 week effort
  - No blockers

**Agent 3:**
- `m3.2-05` - Separate domain state from infrastructure
  - Priority: CRITICAL
  - Can start after M3.1 (easier after m3.2-04 but not required)
  - 1 week effort
  - **BLOCKS:** m3.2-06

### **Week 4: Continue Compiler Extraction** (2 agents in parallel)

**Agent 1:**
- `m3.2-02` - Extract NodeBuilder from compiler
  - Priority: CRITICAL
  - **BLOCKED BY:** m3.2-01 (recommended, not required)
  - 4-5 days effort
  - **BLOCKS:** m3.2-03

**Agent 2:**
- Continue `m3.2-05` or `m3.2-07` if not done

### **Week 5: Sequential Compiler Work** (1 agent required)

**Agent 1:**
- `m3.2-03` - Extract StageCompiler from compiler
  - Priority: CRITICAL
  - **BLOCKED BY:** m3.2-01 AND m3.2-02 (**MUST** complete both)
  - 4-5 days effort
  - **BLOCKS:** m3.2-04

**Other agents:**
- Can work on M4 tasks or documentation

### **Week 6: Final Compiler Refactor + Checkpoint** (2 agents in parallel)

**Agent 1:**
- `m3.2-04` - Refactor LangGraphCompiler to orchestration
  - Priority: CRITICAL
  - **BLOCKED BY:** m3.2-01, m3.2-02, m3.2-03 (**MUST** complete all)
  - 2-3 days effort
  - Final compiler refactoring step

**Agent 2:**
- `m3.2-06` - Implement checkpoint/resume capability
  - Priority: CRITICAL
  - **BLOCKED BY:** m3.2-05 (**MUST** complete state separation)
  - 1 week effort
  - User requirement: long-running workflows

---

## Phase 3: M3.3 Performance Optimization (2 weeks)

### **Week 7: Performance Improvements** (2 agents in PARALLEL) ⚡

**Agent 1:**
- `m3.3-01` - Implement async LLM provider interface
  - Priority: CRITICAL
  - Can start after M3.2 complete
  - 1 week effort
  - Target: 2-3× speedup
  - **BLOCKS:** m3.3-03

**Agent 2:**
- `m3.3-02` - Fix N+1 query problem in observability
  - Priority: CRITICAL
  - Recommended after m3.2-07
  - 1 week effort
  - Target: 90%+ query reduction
  - **BLOCKS:** m3.3-03

**Parallelization:** m3.3-01 and m3.3-02 are independent. Run simultaneously.

### **Week 8 (first half): Benchmarking** (1 agent)

**Agent 1:**
- `m3.3-03` - Performance benchmarking and load testing
  - Priority: HIGH
  - **BLOCKED BY:** m3.3-01 AND m3.3-02 (**MUST** complete both)
  - 3-5 days effort
  - Validates performance gains

---

## Dependency Graph

```
M3.1 (Week 1-2) - All parallel
├─ m3.1-01 (Type Safety) ─────────┐
├─ m3.1-02 (TODOs) ───────────────┤
└─ m3.1-03 (Tool Registry) ───────┤
                                  ↓
M3.2 (Week 3-6) - Mixed parallel/sequential
├─ m3.2-01 (StateManager) ────────────┐
│                                     ↓
├─ m3.2-02 (NodeBuilder) ─────────────┤
│                                     ↓
├─ m3.2-03 (StageCompiler) ───────────┤
│                                     ↓
├─ m3.2-04 (Refactor Main) ───────────┤
│                                     │
├─ m3.2-05 (State Separation) ────────┼──┐
│                                     │  ↓
├─ m3.2-06 (Checkpoint) ──────────────┘  │
│                                        │
└─ m3.2-07 (Observability) ──────────────┘ (independent)
                                  ↓
M3.3 (Week 7-8) - Mostly parallel
├─ m3.3-01 (Async LLM) ───────────────┐
│                                     ↓
├─ m3.3-02 (N+1 Queries) ─────────────┤
│                                     ↓
└─ m3.3-03 (Benchmarks) ──────────────┘
```

---

## Critical Path

**Longest sequential dependency chain:** 5.5 weeks

1. M3.1 complete (2 weeks)
2. → m3.2-01 StateManager (3-4 days)
3. → m3.2-02 NodeBuilder (4-5 days)
4. → m3.2-03 StageCompiler (4-5 days)
5. → m3.2-04 Refactor Main (2-3 days)
6. → M3.3 complete (2 weeks)

**Total:** ~5.5 weeks on critical path, but other work happens in parallel.

---

## Optimal Agent Allocation

### **3 Agents Available:**

**Week 1-2:**
- Agent A: m3.1-01 (Type Safety - 2 weeks)
- Agent B: m3.1-02 + m3.1-03 (TODOs + Tool Registry - 3-4 days total)
- Agent C: m3.2-07 (Observability - can start early)

**Week 3-4:**
- Agent A: m3.2-01 → m3.2-02 (StateManager → NodeBuilder)
- Agent B: m3.2-05 (State Separation - 1 week)
- Agent C: Continue m3.2-07 if needed, or M4 tasks

**Week 5-6:**
- Agent A: m3.2-03 → m3.2-04 (StageCompiler → Refactor Main)
- Agent B: m3.2-06 (Checkpoint - 1 week)
- Agent C: M4 tasks or documentation

**Week 7-8:**
- Agent A: m3.3-01 (Async LLM - 1 week)
- Agent B: m3.3-02 (N+1 Queries - 1 week)
- Agent C: m3.3-03 (Benchmarks - 3-5 days, after A+B done)

---

## How to Claim Tasks

### **Check Available Tasks:**
```bash
.claude-coord/claude-coord.sh task-list available
```

### **View Detailed Spec:**
```bash
.claude-coord/task-spec-helpers.sh task-spec m3.1-01
```

### **Claim Task:**
```bash
.claude-coord/claude-coord.sh task-claim $CLAUDE_AGENT_ID m3.1-01
```

### **Check Dependencies:**
Before claiming, verify task dependencies in spec file:
- `BLOCKED BY: None` = can start immediately
- `BLOCKED BY: m3.2-01` = wait for m3.2-01 to complete
- `Parallel: YES` = can run with other tasks
- `Parallel: NO` = must run sequentially

### **Track Progress:**
```bash
# Mark checklist item complete
.claude-coord/task-spec-helpers.sh task-check m3.1-01 "mypy passes"

# View progress
.claude-coord/task-spec-helpers.sh task-progress m3.1-01
```

### **Complete Task:**
```bash
.claude-coord/claude-coord.sh task-complete $CLAUDE_AGENT_ID m3.1-01
```

---

## Task Priority Key

- **P1 (CRITICAL):** Must complete for milestone
- **P2 (HIGH):** Important but not blocking
- **P3 (NORMAL):** Nice to have

---

## Notes

- **Type Safety (m3.1-01)** takes longest in M3.1 (2 weeks) - start first
- **State Separation (m3.2-05)** can start early, doesn't block compiler work
- **Observability (m3.2-07)** is fully independent - great for parallel agent
- **Compiler extraction (m3.2-01→02→03→04)** must be sequential
- **Checkpoint (m3.2-06)** must wait for state separation
- **Performance tasks (m3.3-01, m3.3-02)** run in parallel for maximum efficiency
- **Benchmarks (m3.3-03)** must be last to validate improvements

---

## Success Criteria

**M3.1 Complete When:**
- [ ] 0 type errors (`mypy --strict` passes)
- [ ] 0 TODOs in critical paths
- [ ] Tool registry has clear error messages

**M3.2 Complete When:**
- [ ] Compiler is <400 lines (from 1200+)
- [ ] State is serializable (checkpoint/resume works)
- [ ] Observability backend is swappable

**M3.3 Complete When:**
- [ ] Async LLM provides 2-3× speedup
- [ ] Database queries reduced by 90%+
- [ ] Performance baselines documented

---

**Last Updated:** 2026-01-27
