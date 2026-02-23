# Audit 34: Frontend (React Dashboard & Workflow Studio)

**Scope:** All files under `frontend/src/` -- components, hooks, stores, pages, types, utilities, and tests.

**Total files audited:** ~95 TypeScript/TSX files across 13 directories.

---

## 1. Architecture Overview

The frontend is a single-page React 19 application built with:
- **Vite 7** (build/dev server, base path `/app/`)
- **React Router 7** (client-side routing)
- **Zustand 5 + Immer** (state management with O(1) flat Maps)
- **TanStack Query 5** (REST API caching)
- **@xyflow/react 12** (React Flow for DAG visualization)
- **Tailwind CSS 4 + shadcn/ui** (styling)
- **Vitest 4 + Testing Library** (unit tests)

### Route Structure (`/home/shinelay/meta-autonomous-framework/frontend/src/App.tsx`)
| Path | Component | Purpose |
|------|-----------|---------|
| `/` | `WorkflowList` | Workflow listing with search, filter, sort |
| `/workflow/:workflowId` | `ExecutionView` | Live DAG + timeline + event log |
| `/compare` | `ComparisonView` | Side-by-side workflow comparison |
| `/studio` | `StudioView` | Visual workflow editor (new) |
| `/studio/:name` | `StudioView` | Visual workflow editor (load existing) |
| `/login` | `LoginPage` | API key authentication |

### Data Flow
```
WebSocket /ws/:id  -->  useWorkflowWebSocket  -->  executionStore (Zustand)
REST /api/*         -->  useInitialData / TanStack Query  -->  executionStore
                                                             ^
useDagElements / useTimelineData (derived selectors) <-------+
                                                             |
Components (StageNode, AgentCard, ...) <---------------------+
```

---

## 2. Code Quality

### 2.1 Strengths

**Well-structured state management.** The execution store (`/home/shinelay/meta-autonomous-framework/frontend/src/store/executionStore.ts`) uses flat `Map<string, T>` for stages, agents, LLM calls, and tool calls, providing O(1) lookups. Immer integration with `enableMapSet()` allows immutable updates on Maps/Sets (line 22). The snapshot/event pattern cleanly separates REST-based initialization from WebSocket incremental updates.

**Design store is comprehensive and correct.** The design store (`/home/shinelay/meta-autonomous-framework/frontend/src/store/designStore.ts`, `designTypes.ts`, `designHistory.ts`, `designPersistence.ts`, `designDefaults.ts`) implements a complete undo/redo system with snapshot-based history (max 50 entries), proper serialization/deserialization of workflow configs, and clean separation of concerns across 5 files. The `captureSnapshot` function uses `JSON.parse(JSON.stringify(...))` for deep cloning (line 32 of designHistory.ts) which, while not the most efficient approach, is correct and simple.

**Performance-conscious rendering.** Components use `memo()` appropriately -- `StageNode` and `AgentCard` are memoized. The `useDagElements` hook uses `useMemo` keyed on `[workflow, stages, agents, expandedStages]`. The `useTimelineData` hook builds a `statusFingerprint` string (line 40-49 of `useTimelineData.ts`) to avoid recalculation when only non-visual data changes (e.g., token counts).

**Strong TypeScript typing.** Types in `/home/shinelay/meta-autonomous-framework/frontend/src/types/index.ts` match the Python backend's snake_case convention exactly. Interfaces cover all WebSocket message variants (`WSSnapshot`, `WSEvent`, `WSHeartbeat`) as a discriminated union (`WSMessage`). The `DesignState` interface (297 lines in `designTypes.ts`) is exhaustive.

**Constants are well-organized.** `/home/shinelay/meta-autonomous-framework/frontend/src/lib/constants.ts` centralizes status colors, layout constants, WebSocket reconnection parameters, polling intervals, debounce delays, and accessibility icons.

### 2.2 Issues

**ISSUE-1 (Medium): `useAgentEditor` isDirty check uses JSON serialization on every render.**
- File: `/home/shinelay/meta-autonomous-framework/frontend/src/hooks/useAgentEditor.ts`, line 679
- `const isDirty = JSON.stringify(config) !== initialRef.current;`
- This runs `JSON.stringify` on the full `AgentFormState` (140 fields, 280 lines of type definition) on every render. Should be `useMemo` or use a dirty flag.

**ISSUE-2 (Medium): `useDesignElements` has duplicated layout logic with `computeAutoPositions`.**
- File: `/home/shinelay/meta-autonomous-framework/frontend/src/hooks/useDesignElements.ts`, lines 86-129 and 366-407.
- The layout computation logic (sequential vs. depth-based) is duplicated between `useDesignElements` and `computeAutoPositions`. Should extract into a single shared function.

**ISSUE-3 (Low): `_diffSnapshotEvents` creates new Date for every event.**
- File: `/home/shinelay/meta-autonomous-framework/frontend/src/store/executionStore.ts`, line 155
- `const now = new Date().toISOString()` is called once, but if the function were called frequently, the pattern of iterating all stages/agents/llmCalls/toolCalls in `_diffSnapshotEvents` could be expensive. Currently mitigated by being called only on snapshot updates.

**ISSUE-4 (Low): Large component prop surfaces in DesignNodeData.**
- File: `/home/shinelay/meta-autonomous-framework/frontend/src/hooks/useDesignElements.ts`, lines 11-67
- `DesignNodeData` has 40+ fields. This makes the React Flow node data object very large and complex. Consider grouping related fields into sub-objects.

---

## 3. Security

### 3.1 XSS Prevention -- PASS

No instances of `dangerouslySetInnerHTML`, `innerHTML`, `outerHTML`, `document.write`, `eval()`, or `new Function()` found anywhere in the frontend codebase. All user-generated content is rendered through React's built-in escaping. Markdown is rendered via `react-markdown` with `remarkGfm` plugin (`/home/shinelay/meta-autonomous-framework/frontend/src/components/shared/MarkdownDisplay.tsx`), which does not inject raw HTML.

### 3.2 API Key Handling -- GOOD with one note

**Good:** API keys are stored in `localStorage` as `temper_api_key` and sent as Bearer tokens via `authFetch()` (`/home/shinelay/meta-autonomous-framework/frontend/src/lib/authFetch.ts`). WebSocket authentication uses short-lived tickets (`/api/auth/ws-ticket`) instead of sending API keys in the WebSocket URL -- this prevents key leakage into server logs and browser history (comment in `useWorkflowWebSocket.ts`, lines 29-36).

**Good:** The `authFetch` wrapper handles 401 responses by clearing the stored key and redirecting to `/app/login` (line 28-31). 403 responses show a toast notification.

**Good:** The login page (`/home/shinelay/meta-autonomous-framework/frontend/src/pages/LoginPage.tsx`) uses `type="password"` for the API key input and validates by making a test request before storing.

**Note:** `import.meta.env.VITE_API_KEY` is referenced as a build-time fallback (line 11 of `authFetch.ts`). This bakes the API key into the JavaScript bundle at build time. If the production build is served publicly, this key would be visible to anyone inspecting the bundle. This is acceptable for dev-only workflows but should be documented as not suitable for production multi-tenant deployments.

### 3.3 WebSocket Security -- GOOD

WebSocket reconnection uses exponential backoff with configurable limits (`WS_INITIAL_DELAY_MS=1000`, `WS_MAX_DELAY_MS=30000`, `WS_BACKOFF_MULTIPLIER=2`). The `onclose` handler properly guards against reconnection after unmount via `unmountedRef`. The cleanup function nulls out `ws.onclose` before calling `ws.close()` to prevent zombie reconnects (line 123 of `useWorkflowWebSocket.ts`).

---

## 4. Error Handling

### 4.1 Error Boundaries -- GOOD

Two error boundaries exist:
1. **App-level** (`/home/shinelay/meta-autonomous-framework/frontend/src/App.tsx`, lines 15-45): Class component wrapping all routes with "Try again" button.
2. **Component-level** (`/home/shinelay/meta-autonomous-framework/frontend/src/components/shared/ErrorBoundary.tsx`): Reusable boundary used in `ExecutionView` around each tab's content (DAG, Timeline, EventLog, LLMCalls) at lines 89-98.

### 4.2 API Error Handling -- GOOD

- `useInitialData` checks `r.ok` before parsing (line 27).
- `useStudioAPI`'s `fetchJSON` wrapper reads error text on non-ok responses (lines 34-38).
- `WorkflowList` displays error state via `EmptyState` component.
- `ComparisonView` query functions call `.json()` without checking status -- **ISSUE-5 (Low)** at line 141-143 of `ComparisonView.tsx`. The `queryFn` for `queryA`, `queryB`, and `queryC` does `(await authFetch(...)).json()` without checking `res.ok` first. A 404 response would result in a JSON parse error rather than a clean error message.

### 4.3 Loading States -- GOOD

- `ExecutionView` shows a `LoadingSkeleton` while waiting for data.
- `StudioView` shows loading/error states for config fetches.
- `WorkflowList` shows `EmptyState` for loading, error, empty, and filtered-empty states (4 distinct states).
- `AgentDetailPanel` shows "Agent not found" via `EmptyState` for missing agents.

### 4.4 WebSocket Error Handling

Malformed WebSocket messages are silently ignored (`catch` in `ws.onmessage`, line 68 of `useWorkflowWebSocket.ts`). This is appropriate -- logging would be noisy during development. The `ws.onerror` handler delegates to `ws.onclose` which handles reconnection.

---

## 5. Modularity & State Management

### 5.1 Store Design -- EXCELLENT

**Execution store:** Single Zustand store with Immer middleware. Uses flat Maps for O(1) lookups by ID. Actions (`applySnapshot`, `applyEvent`, `select`, `reset`, etc.) are well-scoped. The `applyEvent` method handles 8 event types via a clean switch statement. Event log is bounded at `MAX_EVENT_LOG_SIZE=1000` entries (line 312).

**Design store:** Separate Zustand store for the Studio editor. Proper undo/redo with history stacks capped at 50 snapshots. Every mutation captures a snapshot before modifying state. The `renameStage` action correctly updates all references in `depends_on`, `loops_back_to`, and `nodePositions`.

**Selectors:** `/home/shinelay/meta-autonomous-framework/frontend/src/store/selectors.ts` provides `selectStageGroups` (groups stages by name for iteration support) and `selectDagInfo` (extracts topology from config).

### 5.2 Hook Design -- GOOD

Hooks are well-scoped:
- `useWorkflowWebSocket`: WebSocket lifecycle with reconnection
- `useInitialData`: REST fallback with WS race handling
- `useDagElements`: Execution store to React Flow node/edge transform
- `useDesignElements`: Design store to React Flow node/edge transform
- `useTimelineData`: Execution store to timeline row transform
- `useAgentEditor`: Agent form state lifecycle (fetch, parse, edit, save, validate)
- `useResolveStageAgents`: Batch-fetch stage/agent configs for Studio enrichment
- `useKeyboardShortcuts`: Keyboard navigation (1-4 for tab switch, Esc to clear, ? for help)
- `useDebounce`: Generic debounce

### 5.3 Component Composition -- GOOD

Components are appropriately sized. The largest components are:
- `StageNode` (~318 lines): Complex but justified -- handles iteration picker, agent display, metrics, output preview, error display, and React Flow handles.
- `AgentDetailPanel` (~253 lines): Rich detail view with metrics grid, token bar, streaming panel, collapsible sections.
- `WorkflowDetailPanel` (~226 lines): Export buttons, metrics, stage breakdown, tool analytics.
- `WorkflowList` (~286 lines): Search, filter, sort, comparison selection.

No components exceed 320 lines. No dead components detected.

---

## 6. Feature Completeness

### 6.1 TODOs/FIXMEs

Zero TODOs, FIXMEs, HACKs, or XXXs found across the entire frontend codebase. This is clean.

### 6.2 Partial Implementations

All features appear complete. The Studio editor has full CRUD for workflows and agents, the execution view handles all WebSocket event types, and the comparison view supports 2-3 workflow comparison with stage-level diff.

### 6.3 Feature Coverage

The frontend covers:
- Real-time workflow execution monitoring (DAG, timeline, event log, LLM calls table)
- Live streaming content display (thinking + content separation)
- Stage iteration navigation (loop-back support with prev/next)
- Agent detail inspection with live refresh
- LLM call and tool call inspection
- Workflow comparison (2-3 workflows, stage-level metrics diff)
- Visual workflow editor (Studio) with drag-and-drop, undo/redo, validation, save/load
- Agent config editor (16 sections: prompt, inference, tools, safety, memory, error handling, reasoning, observability, context management, output schema, guardrails, pre-commands, merit, persistent, dialogue, metadata)
- API key authentication with localStorage persistence
- Light/dark theme toggle with system preference detection
- Keyboard shortcuts
- Data export (JSON, CSV, Markdown)
- WebSocket reconnection with exponential backoff

---

## 7. Test Quality

### 7.1 Test Coverage

Test files found:
| File | Tests | Coverage |
|------|-------|----------|
| `__tests__/executionStore.test.ts` | ~25 tests | Snapshot, all event types, streaming, selection, WS status |
| `__tests__/components.test.tsx` | ~15 tests | StatusBadge, LLMCallInspector, ToolCallInspector, StreamingPanel, store-component integration |
| `__tests__/output-display.test.tsx` | 7 tests | OutputDisplay rendering, expand/collapse, edge cases |
| `__tests__/fixtures.ts` | N/A | Shared test fixtures matching backend shapes |
| `__tests__/setup.ts` | N/A | jsdom setup with `scrollIntoView` polyfill |

**Total: ~47 tests across 3 test files.**

### 7.2 Coverage Gaps

**ISSUE-6 (Medium): No tests for the design store (Studio).** The `designStore`, `designHistory`, `designPersistence`, and `designDefaults` modules have zero test coverage. These contain complex logic:
- Undo/redo with snapshot stacks
- Config serialization/deserialization (380+ lines of round-trip logic in `designPersistence.ts`)
- Stage rename with reference updates

**ISSUE-7 (Medium): No tests for hooks.** None of the 9 custom hooks have unit tests. The most critical untested hooks are:
- `useWorkflowWebSocket`: WebSocket lifecycle, reconnection logic
- `useAgentEditor`: Form state parsing/serialization (717 lines)
- `useResolveStageAgents`: Batch fetch with inflight deduplication

**ISSUE-8 (Low): No tests for utility functions.** `/home/shinelay/meta-autonomous-framework/frontend/src/lib/utils.ts` has 10 utility functions (formatDuration, formatTokens, formatCost, ensureUTC, categorizeError, extractOutputPreview, formatBytes, truncateLines, formatTimestamp, elapsedSeconds) with zero test coverage.

**ISSUE-9 (Low): No tests for pages.** `WorkflowList`, `ComparisonView`, `LoginPage`, `StudioView`, and `ExecutionView` have no tests.

**ISSUE-10 (Low): No integration/E2E tests configured.** Playwright is in devDependencies but `playwright.config.ts` exists as a skeleton. The `test-*.mjs` files in the frontend root appear to be manual test scripts, not automated tests.

---

## 8. Architectural Gaps

### 8.1 No Route-Level Code Splitting

**ISSUE-11 (Medium): No lazy loading of route components.** All page components (`ExecutionView`, `WorkflowList`, `ComparisonView`, `StudioView`, `LoginPage`) are eagerly imported in `App.tsx` (lines 3-7). The Studio editor alone imports React Flow, dozens of property panel components, and the full design store. Using `React.lazy()` with `Suspense` would improve initial load time for users who only visit the workflow list.

### 8.2 Limited Responsive Design

**ISSUE-12 (Low): Minimal responsive design.** Only 16 responsive-related patterns found across 8 files (mostly `sm:`, `md:` breakpoints in shadcn components). The main layout uses fixed-width panels (`LEFT_WIDTH=200`, `RIGHT_WIDTH=320` in StudioPage.tsx). The `#root` element uses `100vw`/`100vh` with `overflow: hidden` (`index.css` line 159-163), which works well for desktop but would be problematic on small screens. The `WorkflowList` header uses `flex-wrap` (line 122) which helps.

### 8.3 Accessibility

**Accessibility is above average** with 77 ARIA attribute usages across 23 files:
- `aria-label` on buttons (back, expand, collapse, theme toggle)
- `aria-pressed` on toggle buttons (status filter, sort buttons)
- `aria-expanded` on collapsible sections
- `role="button"` and `role="link"` on interactive elements
- `role="group"` on button groups
- Keyboard navigation: Tab/Shift+Tab for DAG nodes, Enter to select, Escape to clear, 1-4 for tab switching
- Focus styles on all interactive elements (`focus:outline-none focus:ring-2 focus:ring-temper-accent/50`)

**ISSUE-13 (Low): Colorblind accessibility.** Status icons exist in `STATUS_ICONS` constant (`/home/shinelay/meta-autonomous-framework/frontend/src/lib/constants.ts`, lines 72-77) with checkmark/play/cross/circle, but `StatusBadge` uses colors as the primary differentiator. The icons should be displayed alongside or instead of color-only status indicators.

### 8.4 No Request Deduplication for `useResolveStageAgents`

**ISSUE-14 (Low):** The `useResolveStageAgents` hook (`/home/shinelay/meta-autonomous-framework/frontend/src/hooks/useResolveStageAgents.ts`) uses raw `fetch()` instead of `authFetch()` for stage/agent config resolution (lines 126 and 237). This means:
1. These requests skip authentication headers.
2. These requests bypass the 401/403 error handling in `authFetch`.

This works when `auth_enabled = False` (dev mode) but would fail silently in production with auth enabled.

---

## 9. Summary Table

| Dimension | Rating | Notes |
|-----------|--------|-------|
| Code Quality | A | Strong TypeScript, well-organized stores and hooks, memoization |
| Security | A | No XSS vectors, proper auth flow, WS ticket auth |
| Error Handling | A- | Error boundaries, API error handling, loading states; minor gap in ComparisonView |
| Modularity | A | Clean store/hook/component separation, appropriate file sizes |
| Feature Completeness | A+ | No TODOs, complete feature set, comprehensive Studio editor |
| Test Quality | C+ | Good execution store tests but major gaps in design store, hooks, utils, pages |
| Accessibility | B+ | Above-average ARIA usage, keyboard nav; colorblind and responsive gaps |

---

## 10. Prioritized Recommendations

### High Priority
1. **Add design store tests** (ISSUE-6): Write unit tests for `designHistory.ts` (undo/redo), `designPersistence.ts` (serialization round-trip), and `designStore.ts` (stage CRUD, rename with reference updates).
2. **Add utility function tests** (ISSUE-8): `formatDuration`, `ensureUTC`, `categorizeError`, `extractOutputPreview` are used throughout -- a test file would catch regressions.
3. **Fix `useResolveStageAgents` to use `authFetch`** (ISSUE-14): Replace raw `fetch()` with `authFetch()` in lines 126 and 237 to ensure auth headers and error handling work in production.

### Medium Priority
4. **Add route-level code splitting** (ISSUE-11): Wrap `StudioView` and `ComparisonView` imports with `React.lazy()` and `Suspense` to reduce initial bundle size.
5. **Fix `useAgentEditor` isDirty performance** (ISSUE-1): Replace `JSON.stringify(config) !== initialRef.current` with a simple boolean flag toggled on `updateField` calls.
6. **Add hook tests** (ISSUE-7): Priority on `useAgentEditor` (complex parsing/serialization) and `useWorkflowWebSocket` (lifecycle management).
7. **Fix ComparisonView query error handling** (ISSUE-5): Add `.ok` check before `.json()` in queryFn callbacks.

### Low Priority
8. **Deduplicate layout logic** (ISSUE-2): Extract shared depth-based layout algorithm from `useDesignElements`.
9. **Add responsive breakpoints** (ISSUE-12): Add mobile-friendly panel collapsing and stack layout for small screens.
10. **Display status icons alongside colors** (ISSUE-13): Use `STATUS_ICONS` in `StatusBadge` component for colorblind accessibility.

---

## 11. File Inventory

### Stores (6 files)
- `/home/shinelay/meta-autonomous-framework/frontend/src/store/executionStore.ts` (494 lines)
- `/home/shinelay/meta-autonomous-framework/frontend/src/store/designStore.ts` (336 lines)
- `/home/shinelay/meta-autonomous-framework/frontend/src/store/designTypes.ts` (298 lines)
- `/home/shinelay/meta-autonomous-framework/frontend/src/store/designHistory.ts` (73 lines)
- `/home/shinelay/meta-autonomous-framework/frontend/src/store/designPersistence.ts` (381 lines)
- `/home/shinelay/meta-autonomous-framework/frontend/src/store/designDefaults.ts` (161 lines)
- `/home/shinelay/meta-autonomous-framework/frontend/src/store/selectors.ts` (75 lines)

### Hooks (9 files)
- `/home/shinelay/meta-autonomous-framework/frontend/src/hooks/useWorkflowWebSocket.ts` (132 lines)
- `/home/shinelay/meta-autonomous-framework/frontend/src/hooks/useInitialData.ts` (42 lines)
- `/home/shinelay/meta-autonomous-framework/frontend/src/hooks/useDagElements.ts` (207 lines)
- `/home/shinelay/meta-autonomous-framework/frontend/src/hooks/useTimelineData.ts` (158 lines)
- `/home/shinelay/meta-autonomous-framework/frontend/src/hooks/useKeyboardShortcuts.ts` (57 lines)
- `/home/shinelay/meta-autonomous-framework/frontend/src/hooks/useAgentEditor.ts` (717 lines)
- `/home/shinelay/meta-autonomous-framework/frontend/src/hooks/useStudioAPI.ts` (142 lines)
- `/home/shinelay/meta-autonomous-framework/frontend/src/hooks/useDesignElements.ts` (408 lines)
- `/home/shinelay/meta-autonomous-framework/frontend/src/hooks/useResolveStageAgents.ts` (299 lines)
- `/home/shinelay/meta-autonomous-framework/frontend/src/hooks/useDebounce.ts` (14 lines)

### Pages (5 files)
- `/home/shinelay/meta-autonomous-framework/frontend/src/pages/ExecutionView.tsx` (121 lines)
- `/home/shinelay/meta-autonomous-framework/frontend/src/pages/WorkflowList.tsx` (286 lines)
- `/home/shinelay/meta-autonomous-framework/frontend/src/pages/ComparisonView.tsx` (198 lines)
- `/home/shinelay/meta-autonomous-framework/frontend/src/pages/LoginPage.tsx` (82 lines)
- `/home/shinelay/meta-autonomous-framework/frontend/src/pages/StudioView.tsx` (55 lines)

### Tests (5 files)
- `/home/shinelay/meta-autonomous-framework/frontend/src/__tests__/executionStore.test.ts` (451 lines, ~25 tests)
- `/home/shinelay/meta-autonomous-framework/frontend/src/__tests__/components.test.tsx` (243 lines, ~15 tests)
- `/home/shinelay/meta-autonomous-framework/frontend/src/__tests__/output-display.test.tsx` (55 lines, 7 tests)
- `/home/shinelay/meta-autonomous-framework/frontend/src/__tests__/fixtures.ts` (282 lines)
- `/home/shinelay/meta-autonomous-framework/frontend/src/__tests__/setup.ts` (5 lines)
