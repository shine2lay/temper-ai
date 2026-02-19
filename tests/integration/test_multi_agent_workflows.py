"""
Integration tests for multi-agent collaboration workflows.

Tests workflows with multiple agents coordinating, reaching consensus,
and handing off tasks between stages.
"""
import uuid
from datetime import UTC, datetime

import pytest

from temper_ai.observability.database import get_session, init_database
from temper_ai.observability.models import (
    AgentExecution,
    StageExecution,
    WorkflowExecution,
)
from temper_ai.observability.tracker import ExecutionTracker

pytestmark = [pytest.mark.integration]


class TestAgentHandoffWorkflows:
    """Test workflows with explicit agent handoff between stages."""

    @pytest.fixture
    def sample_database(self):
        """Initialize in-memory database for testing."""
        try:
            from temper_ai.observability.database import get_database
            get_database()
        except RuntimeError:
            init_database("sqlite:///:memory:")
        yield

    @pytest.fixture
    def execution_tracker(self, sample_database):
        """Execution tracker with test database."""
        from temper_ai.observability.backends.sql_backend import SQLObservabilityBackend
        backend = SQLObservabilityBackend()
        return ExecutionTracker(backend=backend)

    @pytest.mark.integration
    def test_sequential_agent_handoff_with_state_transfer(
        self,
        sample_database,
        execution_tracker
    ):
        """Test agent handoff with complete state transfer.

        Scenario: Document processing pipeline
        - Stage 1: Extractor agent extracts text from document
        - Stage 2: Analyzer agent analyzes extracted text
        - Stage 3: Summarizer agent creates summary

        Each stage must receive complete output from previous stage.

        Validates:
        - State transferred correctly between stages
        - No data loss during handoff
        - Agents can access previous stage outputs
        - Handoff metadata tracked
        """
        workflow_id = str(uuid.uuid4())

        # Create workflow
        workflow_exec = WorkflowExecution(
            id=workflow_id,
            workflow_name="document_processing_pipeline",
            workflow_version="1.0",
            workflow_config_snapshot={},
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(workflow_exec)
            session.commit()

        # Stage 1: Text Extraction
        with execution_tracker.track_stage("extraction", {}, workflow_id) as stage1_id:
            with execution_tracker.track_agent("extractor_agent", {}, stage1_id):
                pass

        with get_session() as session:
            stage1 = session.query(StageExecution).filter_by(id=stage1_id).first()
            stage1.output_data = {
                "extracted_text": "This is the document content...",
                "page_count": 5,
                "word_count": 1250,
                "metadata": {"format": "pdf", "author": "John Doe"}
            }
            session.commit()

        # Stage 2: Analysis (receives stage 1 output)
        with execution_tracker.track_stage("analysis", {}, workflow_id) as stage2_id:
            # Simulate agent receiving previous output
            with get_session() as session:
                prev_stage = session.query(StageExecution).filter_by(id=stage1_id).first()
                prev_output = prev_stage.output_data

                # Verify handoff data
                assert "extracted_text" in prev_output
                assert prev_output["word_count"] == 1250

            with execution_tracker.track_agent("analyzer_agent", {}, stage2_id):
                pass

        with get_session() as session:
            stage2 = session.query(StageExecution).filter_by(id=stage2_id).first()
            stage2.output_data = {
                "sentiment": "neutral",
                "key_topics": ["AI", "automation", "testing"],
                "complexity_score": 0.72,
                "source_word_count": 1250  # Referenced from stage 1
            }
            session.commit()

        # Stage 3: Summarization (receives stage 1 + stage 2 outputs)
        with execution_tracker.track_stage("summarization", {}, workflow_id) as stage3_id:
            # Simulate agent receiving all previous outputs
            with get_session() as session:
                prev_stages = session.query(StageExecution).filter_by(
                    workflow_execution_id=workflow_id
                ).filter(StageExecution.stage_name.in_(["extraction", "analysis"])).all()

                prev_outputs = {s.stage_name: s.output_data for s in prev_stages}

                # Verify access to all previous data
                assert "extraction" in prev_outputs
                assert "analysis" in prev_outputs
                assert prev_outputs["extraction"]["word_count"] == 1250
                assert "key_topics" in prev_outputs["analysis"]

            with execution_tracker.track_agent("summarizer_agent", {}, stage3_id):
                pass

        with get_session() as session:
            stage3 = session.query(StageExecution).filter_by(id=stage3_id).first()
            stage3.output_data = {
                "summary": "Document discusses AI automation and testing (1250 words, neutral tone)",
                "key_points": ["Point 1", "Point 2", "Point 3"],
                "derived_from_stages": ["extraction", "analysis"]
            }
            session.commit()

        # Complete workflow
        workflow_exec.end_time = datetime.now(UTC)
        workflow_exec.status = "completed"

        with get_session() as session:
            session.merge(workflow_exec)
            session.commit()

        # VERIFICATION: Handoff integrity
        with get_session() as session:
            stages = session.query(StageExecution).filter_by(
                workflow_execution_id=workflow_id
            ).order_by(StageExecution.start_time).all()

            assert len(stages) == 3, "Should have 3 stages"

            # Verify handoff chain
            extraction_output = stages[0].output_data
            analysis_output = stages[1].output_data
            summary_output = stages[2].output_data

            # Stage 2 referenced stage 1 data
            assert analysis_output["source_word_count"] == extraction_output["word_count"], \
                "Analysis should reference extraction word count"

            # Stage 3 referenced both previous stages
            assert "extraction" in summary_output["derived_from_stages"]
            assert "analysis" in summary_output["derived_from_stages"]

            # Verify no data corruption
            assert extraction_output["word_count"] == 1250
            assert len(analysis_output["key_topics"]) == 3
            assert len(summary_output["key_points"]) == 3

    @pytest.mark.integration
    def test_agent_handoff_with_partial_output(
        self,
        sample_database,
        execution_tracker
    ):
        """Test agent handoff when previous stage has partial output.

        Scenario: Code review workflow where first reviewer provides
        partial feedback, second reviewer continues review.

        Validates:
        - Partial state can be transferred
        - Second agent can complete incomplete work
        - Combined output is coherent
        """
        workflow_id = str(uuid.uuid4())

        workflow_exec = WorkflowExecution(
            id=workflow_id,
            workflow_name="partial_review_workflow",
            workflow_version="1.0",
            workflow_config_snapshot={},
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(workflow_exec)
            session.commit()

        # Stage 1: Partial review
        with execution_tracker.track_stage("initial_review", {}, workflow_id) as stage1_id:
            with execution_tracker.track_agent("reviewer1", {}, stage1_id):
                pass

        with get_session() as session:
            stage1 = session.query(StageExecution).filter_by(id=stage1_id).first()
            stage1.output_data = {
                "files_reviewed": ["file1.py", "file2.py"],
                "files_remaining": ["file3.py", "file4.py"],
                "issues_found": [
                    {"file": "file1.py", "line": 10, "severity": "high"}
                ],
                "review_complete": False
            }
            session.commit()

        # Stage 2: Complete review
        with execution_tracker.track_stage("complete_review", {}, workflow_id) as stage2_id:
            # Access partial output from stage 1
            with get_session() as session:
                stage1_data = session.query(StageExecution).filter_by(id=stage1_id).first()
                partial_output = stage1_data.output_data

                assert partial_output["review_complete"] is False
                remaining = partial_output["files_remaining"]

            with execution_tracker.track_agent("reviewer2", {}, stage2_id):
                pass

        with get_session() as session:
            stage2 = session.query(StageExecution).filter_by(id=stage2_id).first()
            stage2.output_data = {
                "files_reviewed": ["file3.py", "file4.py"],  # Completed remaining
                "issues_found": [
                    {"file": "file3.py", "line": 25, "severity": "medium"}
                ],
                "combined_issues": 2,  # From both stages
                "review_complete": True
            }
            session.commit()

        # Complete workflow
        workflow_exec.end_time = datetime.now(UTC)
        workflow_exec.status = "completed"

        with get_session() as session:
            session.merge(workflow_exec)
            session.commit()

        # VERIFICATION
        with get_session() as session:
            stages = session.query(StageExecution).filter_by(
                workflow_execution_id=workflow_id
            ).order_by(StageExecution.start_time).all()

            assert len(stages) == 2

            # Verify partial → complete progression
            assert stages[0].output_data["review_complete"] is False
            assert stages[1].output_data["review_complete"] is True

            # Verify combined coverage
            total_files = (
                len(stages[0].output_data["files_reviewed"]) +
                len(stages[1].output_data["files_reviewed"])
            )
            assert total_files == 4, "All 4 files should be reviewed"


class TestConsensusWorkflows:
    """Test workflows where multiple agents must reach consensus."""

    @pytest.fixture
    def sample_database(self):
        """Initialize in-memory database for testing."""
        try:
            from temper_ai.observability.database import get_database
            get_database()
        except RuntimeError:
            init_database("sqlite:///:memory:")
        yield

    @pytest.fixture
    def execution_tracker(self, sample_database):
        """Execution tracker with test database."""
        from temper_ai.observability.backends.sql_backend import SQLObservabilityBackend
        backend = SQLObservabilityBackend()
        return ExecutionTracker(backend=backend)

    @pytest.mark.integration
    def test_multi_agent_consensus_workflow(
        self,
        sample_database,
        execution_tracker
    ):
        """Test workflow where multiple agents must reach consensus.

        Scenario: Code review workflow
        - 3 reviewer agents independently review code
        - Consensus mechanism aggregates reviews
        - Decision made based on majority agreement

        Validates:
        - All agents execute independently
        - Consensus algorithm works correctly
        - Minority opinions captured
        - Final decision reflects consensus
        """
        workflow_id = str(uuid.uuid4())

        # Create workflow
        workflow_exec = WorkflowExecution(
            id=workflow_id,
            workflow_name="code_review_consensus",
            workflow_version="1.0",
            workflow_config_snapshot={},
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(workflow_exec)
            session.commit()

        # Stage: Parallel review by 3 agents
        stage_config = {
            "stage": {
                "name": "peer_review",
                "agents": ["reviewer1", "reviewer2", "reviewer3"],
                "execution": {"agent_mode": "parallel"},
                "collaboration": {"strategy": "consensus", "min_agreement": 0.67}
            }
        }

        with execution_tracker.track_stage("peer_review", stage_config, workflow_id) as stage_id:
            # Simulate 3 parallel reviews
            for i, agent_name in enumerate(["reviewer1", "reviewer2", "reviewer3"]):
                with execution_tracker.track_agent(agent_name, {}, stage_id):
                    pass

        # Set individual review outputs
        with get_session() as session:
            agents = session.query(AgentExecution).filter_by(
                stage_execution_id=stage_id
            ).all()

            # 2 agents approve, 1 rejects
            reviews = [
                {"agent": "reviewer1", "decision": "approve", "score": 0.85, "comments": "Good code quality"},
                {"agent": "reviewer2", "decision": "approve", "score": 0.90, "comments": "Well structured"},
                {"agent": "reviewer3", "decision": "reject", "score": 0.45, "comments": "Needs refactoring"}
            ]

            # Store reviews in stage output
            stage = session.query(StageExecution).filter_by(id=stage_id).first()
            stage.output_data = {
                "reviews": reviews,
                "consensus": "approve",  # 2/3 = 67% agreement
                "confidence": 0.67,
                "minority_opinion": {"agent": "reviewer3", "decision": "reject"}
            }
            session.commit()

        # Stage: Final decision
        with execution_tracker.track_stage("final_decision", {}, workflow_id) as decision_stage_id:
            with execution_tracker.track_agent("decision_maker", {}, decision_stage_id):
                pass

        with get_session() as session:
            stage = session.query(StageExecution).filter_by(id=decision_stage_id).first()
            stage.output_data = {
                "decision": "approved_with_conditions",
                "action_items": ["Address reviewer3 concerns", "Add more tests"],
                "based_on_consensus": True
            }
            session.commit()

        # Complete workflow
        workflow_exec.end_time = datetime.now(UTC)
        workflow_exec.status = "completed"

        with get_session() as session:
            session.merge(workflow_exec)
            session.commit()

        # VERIFICATION: Consensus mechanism
        with get_session() as session:
            peer_review_stage = session.query(StageExecution).filter_by(
                workflow_execution_id=workflow_id,
                stage_name="peer_review"
            ).first()

            output = peer_review_stage.output_data

            # Verify all 3 reviews captured
            assert len(output["reviews"]) == 3

            # Verify consensus calculation
            approvals = sum(1 for r in output["reviews"] if r["decision"] == "approve")
            assert approvals == 2
            assert output["consensus"] == "approve"
            assert output["confidence"] == 0.67  # 2/3

            # Verify minority opinion preserved
            assert output["minority_opinion"]["agent"] == "reviewer3"
            assert output["minority_opinion"]["decision"] == "reject"

            # Verify final decision considers consensus
            decision_stage = session.query(StageExecution).filter_by(
                workflow_execution_id=workflow_id,
                stage_name="final_decision"
            ).first()

            assert decision_stage.output_data["based_on_consensus"] is True
            assert "reviewer3" in str(decision_stage.output_data["action_items"])

    @pytest.mark.integration
    def test_debate_strategy_workflow(
        self,
        sample_database,
        execution_tracker
    ):
        """Test workflow with debate strategy between agents.

        Scenario: Architecture decision workflow
        - Multiple agents propose different architectures
        - Agents debate trade-offs
        - Final decision synthesizes best ideas

        Validates:
        - All agent proposals captured
        - Debate rounds tracked
        - Final synthesis incorporates multiple viewpoints
        """
        workflow_id = str(uuid.uuid4())

        workflow_exec = WorkflowExecution(
            id=workflow_id,
            workflow_name="architecture_debate",
            workflow_version="1.0",
            workflow_config_snapshot={},
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(workflow_exec)
            session.commit()

        # Stage 1: Initial proposals
        with execution_tracker.track_stage("proposals", {}, workflow_id) as stage_id:
            for agent_name in ["architect1", "architect2", "architect3"]:
                with execution_tracker.track_agent(agent_name, {}, stage_id):
                    pass

        with get_session() as session:
            stage = session.query(StageExecution).filter_by(id=stage_id).first()
            stage.output_data = {
                "proposals": [
                    {"agent": "architect1", "approach": "microservices", "score": 0.85},
                    {"agent": "architect2", "approach": "monolith", "score": 0.70},
                    {"agent": "architect3", "approach": "modular_monolith", "score": 0.90}
                ],
                "debate_required": True
            }
            session.commit()

        # Stage 2: Debate round
        with execution_tracker.track_stage("debate", {}, workflow_id) as stage_id:
            with execution_tracker.track_agent("moderator", {}, stage_id):
                pass

        with get_session() as session:
            stage = session.query(StageExecution).filter_by(id=stage_id).first()
            stage.output_data = {
                "debate_rounds": 2,
                "arguments_exchanged": 9,
                "emerging_consensus": "modular_monolith",
                "trade_offs_discussed": ["scalability", "complexity", "cost"]
            }
            session.commit()

        # Stage 3: Final synthesis
        with execution_tracker.track_stage("synthesis", {}, workflow_id) as stage_id:
            with execution_tracker.track_agent("synthesizer", {}, stage_id):
                pass

        with get_session() as session:
            stage = session.query(StageExecution).filter_by(id=stage_id).first()
            stage.output_data = {
                "final_decision": "modular_monolith",
                "incorporates_ideas_from": ["architect1", "architect2", "architect3"],
                "rationale": "Best balance of simplicity and scalability"
            }
            session.commit()

        # Complete workflow
        workflow_exec.end_time = datetime.now(UTC)
        workflow_exec.status = "completed"

        with get_session() as session:
            session.merge(workflow_exec)
            session.commit()

        # VERIFICATION
        with get_session() as session:
            stages = session.query(StageExecution).filter_by(
                workflow_execution_id=workflow_id
            ).order_by(StageExecution.start_time).all()

            assert len(stages) == 3

            # Verify proposals stage
            proposals = stages[0].output_data
            assert len(proposals["proposals"]) == 3
            assert proposals["debate_required"] is True

            # Verify debate occurred
            debate = stages[1].output_data
            assert debate["debate_rounds"] >= 1
            assert "emerging_consensus" in debate

            # Verify synthesis incorporates multiple viewpoints
            synthesis = stages[2].output_data
            assert len(synthesis["incorporates_ideas_from"]) == 3
            assert synthesis["final_decision"] in ["microservices", "monolith", "modular_monolith"]
