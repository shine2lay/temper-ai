# Change 0157: Standardize File Naming Convention

**Task:** docs-med-consistency-02
**Date:** 2026-01-31
**Author:** agent-1ee1f1

## Summary

Documented file naming convention in CONTRIBUTING.md to standardize documentation file names and eliminate confusion about naming patterns.

## What Changed

### Documentation Updated

**docs/CONTRIBUTING.md:**
- Added "File Naming Convention" section under Documentation
- Defined UPPERCASE.md for main documentation
- Defined lowercase_with_underscores.md for supporting docs
- Provided directory structure examples
- Listed when to use each convention
- Listed naming patterns to avoid

## Implementation Details

### Naming Convention Rules

**Main documentation (`docs/*.md`):**
- UPPERCASE.md for all primary documentation
- Examples: `API_REFERENCE.md`, `CONFIGURATION.md`, `TESTING.md`

**Subdirectory documentation (`docs/*/`):**
- UPPERCASE.md for major documents
- README.md for directory index (GitHub convention)
- lowercase_with_underscores.md for supporting documents

**When to use UPPERCASE:**
- Primary framework documentation
- Major feature guides
- Top-level docs users frequently reference

**When to use lowercase:**
- Supporting documentation within subdirectories
- Examples, tutorials, how-tos
- Archive documents, changelogs
- Internal development docs

**Patterns to avoid:**
- Title-Case.md or Title_Case.md
- mixedCase.md or camelCase.md
- Spaces In Names.md

### Current State Analysis

**Current docs/ directory (79 files):**
- Main docs (docs/*.md): Already all UPPERCASE.md ✅
- Subdirs: Mix of UPPERCASE.md and lowercase.md ✅
- Consistent with documented convention

**No files needed renaming** - convention documents existing practice.

## Testing Performed

- ✅ Reviewed all 79 doc files in repository
- ✅ Verified main docs already follow UPPERCASE.md convention
- ✅ Verified subdirectory docs already follow appropriate conventions
- ✅ Documented existing best practice for future contributors

## Impact

**Before:**
- No documented file naming convention
- Contributors guessed naming patterns
- Inconsistency risk for new files

**After:**
- Clear file naming convention documented
- Contributors know exactly which convention to use
- Examples show correct directory structure
- Rule of thumb helps decision-making

## Risks Mitigated

- **Low Risk Change:** Documentation only
- **No Breaking Changes:** No files renamed, only convention documented
- **Improved Consistency:** Future docs will follow convention

## Files Changed

- `docs/CONTRIBUTING.md` - Added file naming convention section

## Acceptance Criteria Met

- [x] Document naming convention in CONTRIBUTING.md
- [x] Choose convention (UPPERCASE.md for major docs, lowercase for supporting)
- [x] Create file naming guide (with examples and rules)
- [x] Add examples of correct naming (directory structure example included)
- [x] All new docs follow convention (convention matches existing practice)
- [x] Document the convention choice in CONTRIBUTING.md

## Design Decisions

**Why UPPERCASE.md for main docs:**
1. **Visual distinction** - Easy to identify important docs
2. **GitHub convention** - README.md, LICENSE.md, CONTRIBUTING.md
3. **Existing practice** - All current main docs already use this
4. **Searchability** - Easier to find primary documentation

**Why lowercase_with_underscores.md for supporting docs:**
1. **Python convention** - Matches Python file naming
2. **Readability** - Underscores separate words clearly
3. **CLI-friendly** - No spaces, tab-completion works
4. **Scalability** - Works well for many files

**Why document existing practice:**
- Codifies what works well
- Prevents future inconsistency
- Helps new contributors
- No disruptive renaming needed
