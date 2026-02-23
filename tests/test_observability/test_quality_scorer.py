"""Tests for heuristic quality scorer."""

from temper_ai.observability._quality_scorer import (
    SCORE_EMPTY,
    SCORE_FAILED,
    SCORE_NON_EMPTY,
    compute_quality_score,
)


class TestComputeQualityScore:
    def test_failed_status(self):
        assert compute_quality_score("failed", {"data": "x"}) == SCORE_FAILED

    def test_error_status(self):
        assert compute_quality_score("error", "output") == SCORE_FAILED

    def test_completed_none_output(self):
        assert compute_quality_score("completed", None) == SCORE_EMPTY

    def test_completed_empty_string(self):
        assert compute_quality_score("completed", "  ") == SCORE_EMPTY

    def test_completed_empty_dict(self):
        assert compute_quality_score("completed", {}) == SCORE_EMPTY

    def test_completed_non_empty(self):
        assert compute_quality_score("completed", {"result": "ok"}) == SCORE_NON_EMPTY

    def test_completed_string_output(self):
        assert compute_quality_score("completed", "Hello world") == SCORE_NON_EMPTY
