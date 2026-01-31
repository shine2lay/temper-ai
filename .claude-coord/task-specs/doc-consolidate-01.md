# Task: doc-consolidate-01 - Resolve Duplicate SYSTEM_OVERVIEW Content

**Priority:** P1
**Effort:** 1-2 hours
**Status:** in_progress
**Owner:** agent-1e0126

---

## Summary

Consolidate duplicate system overview and architecture documentation scattered across multiple files. The main issue is that INDEX.md contains a "Visual Guides" section that duplicates architecture diagrams and descriptions that should only be in SYSTEM_OVERVIEW.md.

---

## Files to Modify

- `docs/INDEX.md` - Remove duplicate architecture content, keep only references
- `docs/architecture/SYSTEM_OVERVIEW.md` - Verify as canonical source

---

## Acceptance Criteria

### Core Functionality
- [x] - [ ] Remove duplicate architecture diagrams from INDEX.md
- [ ] Remove duplicate "System Architecture" content from INDEX.md (lines 78-112)
- [ ] Keep INDEX.md as pure navigation/index document
- [ ] Ensure all references point to SYSTEM_OVERVIEW.md as canonical source
- [ ] Verify no other duplicate system architecture content exists

### Documentation Quality
- [ ] INDEX.md remains clear and navigable
- [ ] All cross-references work correctly
- [ ] No broken links introduced
- [ ] Consistent terminology across documents

---

## Implementation Details

**Duplication Found:**

1. **docs/INDEX.md** (lines 78-112)
   - Contains "Visual Guides" section with system architecture diagram
   - Contains "Agent Execution Flow" diagram
   - Contains "Data Flow" diagram
   - All of this duplicates/overlaps with SYSTEM_OVERVIEW.md

2. **docs/architecture/SYSTEM_OVERVIEW.md**
   - Canonical source for architecture diagrams
   - More detailed and comprehensive
   - Should be the single source of truth

**Solution:**
- Remove Visual Guides section from INDEX.md
- Replace with clear references to SYSTEM_OVERVIEW.md
- Keep INDEX.md focused on navigation/indexing

---

## Changes to Make

### Remove from INDEX.md:
```markdown
## Visual Guides

### System Architecture
[ASCII diagram...]

### Agent Execution Flow
[ASCII diagram...]

### Data Flow
[ASCII diagram...]
```

### Replace with:
```markdown
See [System Overview](./architecture/SYSTEM_OVERVIEW.md) for detailed architecture diagrams including:
- High-level system architecture
- Agent execution flow
- Data flow and component interactions
```

---

## Success Metrics

- [ ] Zero duplicate architecture diagrams
- [ ] INDEX.md is <200 lines (currently ~259 lines)
- [ ] All documentation cross-references valid
- [ ] Documentation structure is clear and DRY (Don't Repeat Yourself)

---

## Dependencies

- **Blocked by:** None
- **Blocks:** None

---

## Design References

- DRY principle: Each piece of knowledge should have single, authoritative representation
- Documentation best practices: Index files should navigate, not duplicate content

---

## Notes

- This is part of broader documentation cleanup effort
- Future tasks may consolidate other duplicate content (configuration examples, API references, etc.)
