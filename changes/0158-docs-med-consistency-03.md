# Change 0158: Add Terminology Glossary

**Task:** docs-med-consistency-03
**Date:** 2026-01-31
**Author:** agent-1ee1f1

## Summary

Created comprehensive GLOSSARY.md to standardize terminology across documentation and eliminate confusion between similar terms (agent vs worker, stage vs step, safety vs security, policy vs rule).

## What Changed

### Files Created

**docs/GLOSSARY.md:**
- Comprehensive terminology reference with 30+ terms
- Organized into sections: Core Concepts, Execution Components, Collaboration, Safety & Governance, Observability, Configuration
- "Common Confusions" section addressing agent vs worker, stage vs step, safety vs security, policy vs rule
- Acronyms table with 10 common abbreviations
- Quick reference table for term selection
- Cross-references to related documentation

**docs/INDEX.md:**
- Added glossary link to "Getting Started" section

## Implementation Details

### Core Terminology Defined

**Primary Terms:**
- **Agent** (not worker) - Autonomous AI entity
- **Stage** (not step) - Workflow execution unit
- **Workflow** - Complete execution graph
- **Policy** (not rule) - Safety validation rule
- **Safety** vs **Security** - Unintended harm vs malicious attacks

### Key Sections

1. **Core Concepts** - Agent, Stage, Workflow, Policy, Safety vs Security
2. **Execution Components** - Execution Engine, Tool, LLM
3. **Collaboration Concepts** - Strategy, Conflict Resolution, Synthesis, Convergence
4. **Safety & Governance** - Violation, Approval Workflow, Rollback, Circuit Breaker, Safety Gate
5. **Observability** - Observability, Trace, Metric
6. **Configuration** - YAML Configuration, Template
7. **Common Confusions** - Agent vs Worker, Stage vs Step, Safety vs Security, Policy vs Rule
8. **Acronyms** - LLM, YAML, API, CLI, P0/P1/P2, SSRF, TTL, E2E, ADR
9. **Quick Reference** - Term selection guide

### Common Confusions Resolved

| Confusion | Correct Term | Avoid |
|-----------|-------------|-------|
| AI entity | Agent | Worker |
| Workflow unit | Stage | Step, phase, node |
| Autonomous safety | Safety | (use Security only for attacks) |
| Validation rule | Policy | Rule |

## Testing Performed

- ✅ Reviewed all major documentation files for terminology consistency
- ✅ Verified glossary covers all ambiguous terms
- ✅ Added cross-references to related documentation
- ✅ Linked glossary from docs/INDEX.md

## Impact

**Before:**
- No centralized terminology reference
- Inconsistent use of: worker/agent, step/stage, safety/security, rule/policy
- New users confused by terminology variations
- No guidance on which term to use

**After:**
- Comprehensive glossary with 30+ terms
- Clear guidance on preferred terminology
- "Common Confusions" section addresses frequent issues
- Quick reference table for term selection
- Linked from documentation index

## Risks Mitigated

- **Low Risk Change:** Documentation only
- **No Breaking Changes:** Existing docs unchanged
- **Improved Consistency:** Contributors can reference glossary

## Files Changed

- `docs/GLOSSARY.md` - Created (new file, 300+ lines)
- `docs/INDEX.md` - Added glossary link

## Acceptance Criteria Met

- [x] Create docs/GLOSSARY.md
- [x] Define: agent vs worker (agent is correct term)
- [x] Define: stage vs step (stage is correct term)
- [x] Define: safety vs security (safety=unintended harm, security=attacks)
- [x] Define: policy vs rule (policy is correct term)
- [x] Add to docs index (linked from INDEX.md)
- [x] Glossary covers all ambiguous terms
- [x] Link to glossary from main docs

## Design Decisions

**Glossary Structure:**
1. **Organized by category** - Easier to find related terms
2. **Usage examples** - Shows correct usage in context
3. **"Not" examples** - Explicitly shows terms to avoid
4. **Related terms** - Links concepts together
5. **Common Confusions** - Addresses frequent mistakes upfront
6. **Quick Reference** - Fast lookup table

**Terminology Choices:**
- **Agent** over worker - More accurate for AI entities that reason
- **Stage** over step - Established framework terminology
- **Safety** as primary - Framework focuses on safe autonomous operation
- **Policy** over rule - Industry standard for validation rules

**Cross-references:**
- Links to API_REFERENCE.md, CONFIGURATION.md, ROADMAP.md, CONTRIBUTING.md
- Helps users find detailed information on each concept
