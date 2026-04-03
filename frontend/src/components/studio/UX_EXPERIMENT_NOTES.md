# Studio UX Experiment — Building a Workflow from Scratch

## Date: 2026-04-02

## Experiment: Create a 3-agent workflow (planner → coder → reviewer) entirely through the UI

### Steps Completed
1. ✅ Open empty Studio
2. ✅ Set workflow name to "my_test_workflow"  
3. ✅ Set provider (vllm) and model (qwen3-next) in Settings overlay
4. ✅ Click "planner" in left panel → node created, agent panel opened
5. ✅ Click "coder" in left panel → second node created
6. ✅ Click "reviewer" in left panel → third node created
7. ❌ Try to add dependencies — FAILED (can't access Stage Properties)
8. ❌ Try to go back from agent panel — NAVIGATED TO HOME PAGE
9. ❌ Return to Studio — ALL WORK LOST

### Critical Bugs Found

#### BUG 1: Back button from Agent Properties exits Studio
- **Severity**: Critical
- **Steps**: Click agent in left panel → Agent Properties opens → Click ← back
- **Expected**: Go back to Stage Properties panel
- **Actual**: Navigated to home page, left Studio entirely
- **Root cause**: For single-agent stages, PropertyPanel auto-selects the agent. The AgentPropertiesPanel's back button calls `selectAgent(null)`, which goes back to stage panel, but then the auto-select effect immediately re-selects the agent. This creates a loop that breaks navigation.

#### BUG 2: Unsaved work lost without warning
- **Severity**: Critical  
- **Steps**: Build workflow → Navigate away → Come back
- **Expected**: Workflow still there, or at least a "save before leaving?" prompt
- **Actual**: Empty canvas, all work gone
- **Note**: The `beforeunload` handler exists but didn't trigger (or was ignored by programmatic navigation)

#### BUG 3: No way to set dependencies through agent panel
- **Severity**: High
- **Steps**: Select a single-agent node → Try to add depends_on
- **Expected**: See Dependencies section in right panel
- **Actual**: Agent Properties panel opens (no Dependencies section). Can't get to Stage Properties.
- **Root cause**: Single-agent auto-select always shows agent panel, hiding stage-level config (deps, input wiring, conditions)

### Recommendations

1. **For single-agent nodes**: Show a COMBINED panel — agent config at top, stage config (deps, I/O, conditions) below. Don't separate into two panels.

2. **Auto-save to localStorage**: Periodically save the design store to localStorage. On page load, check if there's unsaved work and offer to restore.

3. **Navigation guard**: Block programmatic navigation (react-router) when there are unsaved changes, not just browser-level `beforeunload`.

4. **Add "Dependencies" to agent panel**: For single-agent stages, show the dependency dropdown directly in the agent properties panel since that's what the user sees.
