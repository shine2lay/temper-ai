"""Metric registry for DSPy prompt optimization."""

from collections.abc import Callable
from typing import Any

MetricFn = Callable[..., Any]

FUZZY_THRESHOLD = 0.5
DEFAULT_JUDGE_RUBRIC = (
    "Score 0.0 to 1.0 based on correctness, completeness, and relevance."
)

_SCORE_MIN = 0.0
_SCORE_MAX = 1.0


def _exact_match_metric(
    example: Any,
    prediction: Any,
    trace: Any = None,
) -> bool:
    """Return True if prediction output matches example output exactly."""
    return getattr(prediction, "output", "") == getattr(example, "output", "")


def _contains_metric(
    example: Any,
    prediction: Any,
    trace: Any = None,
) -> bool:
    """Return True if expected output is a substring of predicted output."""
    expected = str(getattr(example, "output", ""))
    actual = str(getattr(prediction, "output", ""))
    return expected in actual


def _fuzzy_metric(
    example: Any,
    prediction: Any,
    trace: Any = None,
) -> bool:
    """Return True if token overlap ratio >= FUZZY_THRESHOLD."""
    expected = set(str(getattr(example, "output", "")).lower().split())
    actual = set(str(getattr(prediction, "output", "")).lower().split())
    if not expected:
        return not actual
    overlap = len(expected & actual) / len(expected | actual)
    return overlap >= FUZZY_THRESHOLD


def _parse_score(raw: Any) -> float:
    """Extract float from LLM output string, clamped to [0.0, 1.0]."""
    try:
        value = float(str(raw).strip())
    except (ValueError, TypeError):
        return _SCORE_MIN
    return max(_SCORE_MIN, min(_SCORE_MAX, value))


def create_llm_judge_metric(**kwargs: Any) -> MetricFn:
    """Return a metric closure that uses dspy.ChainOfThought to score outputs.

    Accepts optional `rubric` kwarg to customize the judge prompt.
    Returns a callable with signature (example, prediction, trace=None) -> float.
    """
    rubric = kwargs.get("rubric", DEFAULT_JUDGE_RUBRIC)

    def _llm_judge_metric(
        example: Any,
        prediction: Any,
        trace: Any = None,
    ) -> float:
        import dspy  # noqa: PLC0415 — lazy import, dspy is optional

        judge = dspy.ChainOfThought(
            "input, expected_output, actual_output -> score, reasoning",
        )
        result = judge(
            input=str(getattr(example, "input", "")),
            expected_output=str(getattr(example, "output", "")),
            actual_output=str(getattr(prediction, "output", "")),
        )
        raw_score = getattr(result, "score", _SCORE_MIN)
        return _parse_score(raw_score)

    _llm_judge_metric.__doc__ = f"LLM judge metric. Rubric: {rubric}"
    return _llm_judge_metric


def create_gepa_feedback_metric(**kwargs: Any) -> MetricFn:
    """Return a metric closure matching GEPA's 5-param protocol.

    Closure signature: (gold, pred, trace, pred_name, pred_trace) -> ScoreWithFeedback.
    Accepts optional `rubric` kwarg to customize the judge prompt.
    """
    rubric = kwargs.get("rubric", DEFAULT_JUDGE_RUBRIC)

    def _gepa_feedback_metric(
        gold: Any,
        pred: Any,
        trace: Any = None,
        _pred_name: Any = None,  # required by dspy GEPA callback signature
        _pred_trace: Any = None,  # required by dspy GEPA callback signature
    ) -> Any:
        import dspy  # noqa: PLC0415 — lazy import, dspy is optional
        from dspy.teleprompt.gepa.gepa_utils import ScoreWithFeedback  # noqa: PLC0415

        judge = dspy.ChainOfThought(
            "input, expected_output, actual_output -> score, feedback",
        )
        result = judge(
            input=str(getattr(gold, "input", "")),
            expected_output=str(getattr(gold, "output", "")),
            actual_output=str(getattr(pred, "output", "")),
        )
        score = _parse_score(getattr(result, "score", _SCORE_MIN))
        feedback_text = str(getattr(result, "feedback", ""))
        return ScoreWithFeedback(score=score, feedback=feedback_text)

    _gepa_feedback_metric.__doc__ = f"GEPA feedback metric. Rubric: {rubric}"
    return _gepa_feedback_metric


_METRIC_REGISTRY: dict[str, Callable[..., MetricFn]] = {
    "exact_match": lambda **kw: _exact_match_metric,
    "contains": lambda **kw: _contains_metric,
    "fuzzy": lambda **kw: _fuzzy_metric,
    "llm_judge": create_llm_judge_metric,
    "gepa_feedback": create_gepa_feedback_metric,
}


def get_metric(name: str, **kwargs: Any) -> MetricFn:
    """Look up and return a metric function by name.

    Raises ValueError if the name is not registered.
    """
    factory = _METRIC_REGISTRY.get(name)
    if factory is None:
        raise ValueError(
            f"Unknown metric '{name}'. Available: {list_metrics()}",
        )
    return factory(**kwargs)


def register_metric(name: str, factory: Callable[..., MetricFn]) -> None:
    """Register a metric factory under the given name."""
    _METRIC_REGISTRY[name] = factory


def list_metrics() -> list[str]:
    """Return a sorted list of all registered metric names."""
    return sorted(_METRIC_REGISTRY.keys())
