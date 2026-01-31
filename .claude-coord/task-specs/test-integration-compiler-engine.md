# Task: test-integration-compiler-engine - Compiler + Engine + Observability Integration

**Priority:** HIGH
**Effort:** 2-3 days
**Status:** pending
**Owner:** unassigned

---

## Summary
Add integration tests for compiler + execution engine + observability database with real workflow execution.

---

## Files to Create
- `tests/integration/test_compiler_engine_observability.py` - Full integration tests

---

## Acceptance Criteria

### Integration Coverage
- [ ] Test workflow compilation → execution → database tracking
- [ ] Test stage outputs passed between stages correctly
- [ ] Test multi-stage workflow with dependencies
- [ ] Test workflow state serialization/deserialization
- [ ] Test observability metrics collected accurately
- [ ] Test error tracking in database

### Testing
- [ ] 12 integration tests covering full pipeline
- [ ] Tests use real database (not mocks)
- [ ] Tests verify end-to-end data integrity
- [ ] Tests check performance (workflow execution <5s)

---

## Implementation Details

```python
# tests/integration/test_compiler_engine_observability.py

class TestCompilerEngineObservability:
    """Integration tests for compiler + engine + observability."""
    
    @pytest.mark.asyncio
    async def test_full_workflow_execution_tracked(self):
        """Test workflow execution fully tracked in database."""
        # Compile workflow from config
        config = load_test_workflow_config()
        workflow = compile_workflow(config)
        
        # Execute workflow
        result = await workflow.execute()
        
        # Verify in database
        with SessionManager.session() as session:
            execution = session.query(WorkflowExecution).filter_by(
                workflow_id=workflow.id
            ).first()
            
            assert execution is not None
            assert execution.status == "completed"
            assert execution.total_tokens > 0
            assert execution.total_cost_usd > 0
    
    @pytest.mark.asyncio
    async def test_stage_output_propagation(self):
        """Test stage outputs propagate correctly."""
        # Create 3-stage workflow
        # Stage 1 outputs data
        # Stage 2 consumes and transforms
        # Stage 3 uses transformed data
        # Verify data integrity throughout
        pass
```

---

## Success Metrics
- [ ] 12 integration tests implemented
- [ ] End-to-end data integrity verified
- [ ] Performance baselines met
- [ ] Database tracking accurate

---

## Dependencies
- **Blocked by:** test-fix-failures-01, test-fix-failures-03
- **Blocks:** None

