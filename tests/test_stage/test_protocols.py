"""Tests for temper_ai/stage/executors/_protocols.py.

Covers:
- SynthesisCoordinatorProtocol runtime_checkable isinstance
- QualityGateValidatorProtocol runtime_checkable isinstance
- LeaderCapableStrategy runtime_checkable isinstance
- DialogueCapableStrategy runtime_checkable isinstance
- StanceCuratingStrategy runtime_checkable isinstance
"""

from temper_ai.stage.executors._protocols import (
    DialogueCapableStrategy,
    LeaderCapableStrategy,
    QualityGateValidatorProtocol,
    StanceCuratingStrategy,
    SynthesisCoordinatorProtocol,
)


class TestSynthesisCoordinatorProtocol:
    """Tests for SynthesisCoordinatorProtocol."""

    def test_conforming_class(self):
        """Class with synthesize method passes isinstance check."""

        class Good:
            def synthesize(self, agent_outputs, stage_config, stage_name):
                return None

        assert isinstance(Good(), SynthesisCoordinatorProtocol)

    def test_non_conforming_class(self):
        """Class without synthesize method fails isinstance check."""

        class Bad:
            pass

        assert not isinstance(Bad(), SynthesisCoordinatorProtocol)


class TestQualityGateValidatorProtocol:
    """Tests for QualityGateValidatorProtocol."""

    def test_conforming_class(self):
        """Class with validate method passes isinstance check."""

        class Good:
            def validate(self, synthesis_result, stage_config, stage_name):
                return (True, [])

        assert isinstance(Good(), QualityGateValidatorProtocol)

    def test_non_conforming_class(self):
        """Class without validate method fails isinstance check."""

        class Bad:
            def check(self):
                pass

        assert not isinstance(Bad(), QualityGateValidatorProtocol)


class TestLeaderCapableStrategy:
    """Tests for LeaderCapableStrategy."""

    def test_conforming_class(self):
        """Class with all required attributes/methods passes isinstance check."""

        class Good:
            requires_leader_synthesis = True

            def get_leader_agent_name(self, config):
                return "leader"

            def format_team_outputs(self, outputs):
                return ""

        assert isinstance(Good(), LeaderCapableStrategy)

    def test_missing_method_fails(self):
        """Class missing a required method fails isinstance check."""

        class Bad:
            requires_leader_synthesis = True

            def get_leader_agent_name(self, config):
                return "leader"

        assert not isinstance(Bad(), LeaderCapableStrategy)


class TestDialogueCapableStrategy:
    """Tests for DialogueCapableStrategy."""

    def test_conforming_class(self):
        """Class with all required attributes and methods passes isinstance check."""

        class Good:
            requires_requery = True
            max_rounds = 5
            min_rounds = 1
            convergence_threshold = 0.9
            cost_budget_usd = None
            mode = "debate"

            def synthesize(self, agent_outputs, config):
                return None

            def calculate_convergence(self, current, previous):
                return 1.0

        assert isinstance(Good(), DialogueCapableStrategy)

    def test_non_conforming_class(self):
        """Class without required methods fails isinstance check."""

        class Bad:
            requires_requery = True

        assert not isinstance(Bad(), DialogueCapableStrategy)


class TestStanceCuratingStrategy:
    """Tests for StanceCuratingStrategy."""

    def test_conforming_class(self):
        """Class with all required methods passes isinstance check."""

        class Good:
            def curate_dialogue_history(
                self, dialogue_history, current_round, agent_name
            ):
                return []

            def get_round_context(self, round_num, agent_name):
                return {}

            def extract_stances(self, outputs, llm_providers):
                return {}

        assert isinstance(Good(), StanceCuratingStrategy)

    def test_missing_method_fails(self):
        """Class missing a required method fails isinstance check."""

        class Bad:
            def curate_dialogue_history(
                self, dialogue_history, current_round, agent_name
            ):
                return []

        assert not isinstance(Bad(), StanceCuratingStrategy)
