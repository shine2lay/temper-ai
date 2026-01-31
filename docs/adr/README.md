# Architecture Decision Records (ADRs)

This directory contains Architecture Decision Records (ADRs) for the Meta-Autonomous Framework.

---

## What are ADRs?

**Architecture Decision Records (ADRs)** are documents that capture important architectural decisions made in the project, along with their context and consequences.

ADRs help by:
- **Providing context** - Future developers understand why decisions were made
- **Preventing re-litigation** - Avoid endless debates about settled decisions
- **Enabling informed changes** - Understand consequences before modifying architecture
- **Knowledge transfer** - Onboard new team members faster
- **Traceability** - Track evolution of system design over time

---

## ADR Format

Each ADR follows a structured format (see [template.md](./template.md)):

1. **Context** - The situation and problem
2. **Decision Drivers** - Key factors influencing the decision
3. **Considered Options** - Alternatives evaluated
4. **Decision Outcome** - The chosen option and justification
5. **Consequences** - Positive, negative, and neutral impacts
6. **Implementation Notes** - How to implement the decision
7. **Related Decisions** - Links to related ADRs
8. **References** - Supporting documentation

---

## When to Write an ADR

Create an ADR when making decisions about:

### Technical Architecture
- **Execution engines** - Choice of workflow execution backend (LangGraph, custom, etc.)
- **Data storage** - Database selection (SQLite, PostgreSQL, etc.)
- **Communication protocols** - API design, message formats
- **Technology stack** - Programming languages, frameworks, libraries

### System Design
- **Component boundaries** - Module separation and interfaces
- **Integration patterns** - How components interact
- **Concurrency models** - Multi-agent coordination strategies
- **State management** - How state is stored and propagated

### Quality Attributes
- **Performance** - Optimization strategies and tradeoffs
- **Security** - Authentication, authorization, encryption
- **Reliability** - Error handling, retry policies, circuit breakers
- **Scalability** - Horizontal vs vertical scaling approaches

### Process Decisions
- **Testing strategy** - Unit, integration, E2E test approaches
- **Deployment** - CI/CD pipeline, release process
- **Versioning** - API versioning, backward compatibility
- **Dependencies** - Third-party library choices

### When NOT to Write an ADR

Don't create ADRs for:
- **Implementation details** - Specific code patterns (use code comments)
- **Temporary decisions** - Choices easily reversed without impact
- **Obvious choices** - Industry-standard practices with no alternatives
- **Trivial decisions** - Low-impact choices with minimal consequences

---

## How to Create an ADR

### 1. Determine ADR Number

Find the next sequential number:

```bash
# List existing ADRs
ls -1 docs/adr/*.md | grep -E "^docs/adr/[0-9]+" | sort -V | tail -1

# Next number is N+1
```

### 2. Copy Template

```bash
# Copy template to new ADR file
cp docs/adr/template.md docs/adr/NNNN-short-title.md
```

**Naming Convention:**
- `NNNN` - Four-digit sequential number (e.g., 0001, 0002, 0123)
- `short-title` - Lowercase, hyphenated, descriptive slug
- Example: `0001-execution-engine-abstraction.md`

### 3. Fill In Sections

Work through each section of the template:

1. **Title & Metadata** - Date, status, deciders, tags
2. **Context** - Problem statement and background
3. **Decision Drivers** - Key factors (performance, cost, complexity, etc.)
4. **Considered Options** - List 2-4 alternatives with pros/cons
5. **Decision Outcome** - Chosen option with justification
6. **Consequences** - Positive, negative, neutral impacts
7. **Implementation Notes** - Technical details, action items
8. **Related Decisions** - Links to other ADRs
9. **References** - External documentation, research

### 4. Review Process

Before finalizing:

- **Technical review** - Verify technical accuracy
- **Completeness check** - All sections filled meaningfully
- **Link verification** - Related ADRs and references are valid
- **Spelling & grammar** - Professional quality documentation

### 5. Merge and Announce

```bash
# Create change log
# Add ADR file to git
git add docs/adr/NNNN-*.md
git commit -m "docs: Add ADR-NNNN [short title]"

# Update this README if needed (see "Existing ADRs" section below)
```

---

## ADR Lifecycle

### Status Progression

```
[Proposed] → [Accepted] → [Deprecated] → [Superseded]
              ↓
         [Rejected]
```

**Status Definitions:**

- **Proposed** - Decision under discussion, not yet finalized
- **Accepted** - Decision approved and implemented (or in progress)
- **Rejected** - Decision was considered but not adopted
- **Deprecated** - Decision is outdated but still in effect
- **Superseded** - Decision replaced by a newer ADR (link to replacement)

### Updating ADRs

**When to update:**
- Add missing information discovered later
- Correct factual errors
- Add links to related ADRs created afterward
- Document implementation progress

**How to update:**
1. Edit the ADR file
2. Add entry to "Update History" table at bottom
3. Commit with descriptive message
4. Do NOT change the decision itself (create new ADR instead)

**Superseding an ADR:**
1. Create new ADR with updated decision
2. Update old ADR status to "Superseded"
3. Add link in old ADR to new ADR
4. Add link in new ADR back to old ADR

---

## Existing ADRs

| Number | Title | Status | Date | Tags |
|--------|-------|--------|------|------|
| [0001](./0001-execution-engine-abstraction.md) | Execution Engine Abstraction | Accepted | 2026-01-27 | architecture, execution, decoupling, M2.5 |
| [0002](./0002-langgraph-as-initial-engine.md) | LangGraph as Initial Engine | Accepted | 2026-01-26 | execution, langgraph, workflow, M2 |
| [0003](./0003-multi-agent-collaboration-strategies.md) | Multi-Agent Collaboration Strategies | Accepted | 2026-01-26 | collaboration, agents, synthesis, M3 |
| [0004](./0004-observability-database-schema.md) | Observability Database Schema | Accepted | 2026-01-25 | observability, database, tracing, M1 |
| [0005](./0005-yaml-based-configuration.md) | YAML-Based Configuration | Accepted | 2026-01-25 | configuration, yaml, workflows, M1 |

*Note: ADRs 0001-0005 document historical decisions from milestones M1-M3*

---

## Best Practices

### Writing Good ADRs

**DO:**
- ✅ Write in past tense for accepted decisions ("We chose X")
- ✅ Be specific and concrete (avoid vague statements)
- ✅ Include measurable criteria where possible
- ✅ Document alternatives considered (shows due diligence)
- ✅ Link to supporting evidence and references
- ✅ Be honest about negative consequences
- ✅ Keep it concise (2-4 pages maximum)

**DON'T:**
- ❌ Hide negative consequences or risks
- ❌ Present only one option (shows bias)
- ❌ Use jargon without explanation
- ❌ Make it too long (readers won't finish)
- ❌ Skip the context section (loses future readers)
- ❌ Forget to update status when decision changes

### Common Pitfalls

1. **Bias confirmation** - Listing only options that justify pre-made decision
   - Solution: Document options objectively before deciding

2. **Analysis paralysis** - Spending weeks analyzing trivial decisions
   - Solution: Use the "reversibility" test - easily reversible decisions don't need ADRs

3. **Outdated ADRs** - Keeping "Accepted" ADRs when reality has changed
   - Solution: Regular ADR reviews (quarterly), update status

4. **Missing context** - Assuming future readers have current knowledge
   - Solution: Explain background thoroughly, link to external resources

---

## Integration with Project Workflow

### Discovery Phase
- Search existing ADRs before proposing new solutions
- Reference relevant ADRs in design discussions

### Planning Phase
- Identify architectural decisions needed
- Draft ADR for significant decisions

### Implementation Phase
- Update ADR status to "Accepted" when implementation begins
- Reference ADR number in related code comments and PRs

### Review Phase
- Include ADR review in architecture review process
- Verify implementation matches ADR decision

---

## Tools and Automation

### Search ADRs
```bash
# Search by keyword
grep -r "execution engine" docs/adr/*.md

# List by status
grep -h "^**Status:**" docs/adr/*.md | sort | uniq -c

# List by tag
grep -h "^**Tags:**" docs/adr/*.md
```

### Validate ADR Format
```bash
# Check all ADRs have required sections
for file in docs/adr/[0-9]*.md; do
  echo "Checking $file..."
  grep -q "## Context" "$file" || echo "  Missing Context section"
  grep -q "## Decision Outcome" "$file" || echo "  Missing Decision section"
  grep -q "## Consequences" "$file" || echo "  Missing Consequences section"
done
```

### Generate ADR Index
```bash
# Extract ADR metadata for README table
for file in docs/adr/[0-9]*.md; do
  number=$(basename "$file" | cut -d'-' -f1)
  title=$(grep "^# ADR-" "$file" | sed 's/^# ADR-[0-9]*: //')
  status=$(grep "^**Status:**" "$file" | sed 's/^**Status:** //' | sed 's/ *$//')
  echo "| $number | $title | $status |"
done
```

---

## References

### ADR Resources

- **Original ADR concept** - [Michael Nygard's blog post](http://thinkrelevance.com/blog/2011/11/15/documenting-architecture-decisions)
- **ADR GitHub org** - [https://adr.github.io/](https://adr.github.io/)
- **ADR tools** - [https://github.com/npryce/adr-tools](https://github.com/npryce/adr-tools)
- **MADR format** - [Markdown Any Decision Records](https://adr.github.io/madr/)

### Related Project Documentation

- [TECHNICAL_SPECIFICATION.md](../../TECHNICAL_SPECIFICATION.md) - Complete technical specification
- [docs/VISION.md](../VISION.md) - Project vision and philosophy
- [docs/ROADMAP.md](../ROADMAP.md) - Project roadmap and milestones
- [changes/](../../changes/) - Implementation change logs

---

## FAQ

**Q: When should I create an ADR vs a design document?**

A: Create an ADR for **decisions** (choosing between alternatives). Create a design document for **designs** (how to implement a chosen solution).

**Q: Can I modify an accepted ADR?**

A: You can add clarifications and corrections, but not change the decision itself. To change a decision, create a new ADR that supersedes the old one.

**Q: What if we realize an ADR decision was wrong?**

A: Create a new ADR documenting the new decision and link it as superseding the old ADR. The old ADR remains for historical context.

**Q: How detailed should ADRs be?**

A: Include enough detail for someone unfamiliar with the decision to understand the context, options, and rationale. Aim for 2-4 pages.

**Q: Should ADRs be written before or after implementation?**

A: ADRs should be written **before** or **during** implementation for significant decisions, and **after** for decisions discovered to be important in retrospect.

**Q: Can I have multiple ADRs on the same topic?**

A: Yes! As the project evolves, new ADRs can supersede old ones. This shows the evolution of thinking over time.

---

## Contributing

To propose changes to the ADR process itself:

1. Create an ADR documenting the proposed change to the ADR process
2. Discuss in team review
3. Update this README after decision is accepted

---

**Last Updated:** 2026-01-28
**Maintained by:** Framework Core Team
