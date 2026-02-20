"""Tests for code-high-random-assign-38.

Verifies that RandomAssignment uses cryptographic PRNG (SystemRandom)
instead of the predictable Mersenne Twister random module.
"""

import threading
from collections import Counter
from unittest.mock import patch

from temper_ai.experimentation.assignment import RandomAssignment
from temper_ai.experimentation.models import AssignmentStrategyType, Experiment, Variant


def _make_experiment():
    return Experiment(
        id="exp-1",
        name="test",
        description="test",
        strategy=AssignmentStrategyType.RANDOM,
    )


def _make_variants(n=2, equal_traffic=True):
    traffic = 1.0 / n if equal_traffic else None
    variants = []
    for i in range(n):
        variants.append(Variant(
            id=f"variant-{i}",
            name=f"Variant {i}",
            config={"model": f"model-{i}"},
            allocated_traffic=traffic if equal_traffic else (0.5 if i == 0 else 0.5 / (n - 1)),
        ))
    return variants


class TestCryptographicPRNG:
    """Verify RandomAssignment uses SystemRandom."""

    def test_uses_system_random(self):
        """Assignment should use secrets.SystemRandom, not random module."""
        strategy = RandomAssignment()
        experiment = _make_experiment()
        variants = _make_variants()

        # Patch SystemRandom to verify it's called
        with patch("temper_ai.experimentation.assignment.secrets") as mock_secrets:
            mock_rng = mock_secrets.SystemRandom.return_value
            mock_rng.choices.return_value = ["variant-0"]

            result = strategy.assign(experiment, variants, "exec-1")

            mock_secrets.SystemRandom.assert_called_once()
            mock_rng.choices.assert_called_once()
            assert result == "variant-0"

    def test_no_standard_random_import(self):
        """The module should not use the standard random module."""
        import temper_ai.experimentation.assignment as mod
        # 'random' should not be in the module's namespace
        assert not hasattr(mod, 'random')

    def test_uniform_distribution(self):
        """10,000 assignments should produce roughly uniform distribution."""
        strategy = RandomAssignment()
        experiment = _make_experiment()
        variants = _make_variants(n=3, equal_traffic=True)

        counts = Counter()
        for i in range(10000):
            vid = strategy.assign(experiment, variants, f"exec-{i}")
            counts[vid] += 1

        # Each variant should get roughly 3333 assignments (±500)
        for vid in ["variant-0", "variant-1", "variant-2"]:
            assert 2500 < counts[vid] < 4500, (
                f"Variant {vid} got {counts[vid]} assignments, expected ~3333"
            )

    def test_thread_safety(self):
        """Concurrent assignment calls should not raise exceptions."""
        strategy = RandomAssignment()
        experiment = _make_experiment()
        variants = _make_variants(n=4, equal_traffic=True)

        results = []
        errors = []
        barrier = threading.Barrier(20)

        def worker(thread_id):
            try:
                barrier.wait()
                for i in range(100):
                    vid = strategy.assign(experiment, variants, f"exec-{thread_id}-{i}")
                    results.append(vid)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Thread errors: {errors}"
        assert len(results) == 2000  # 20 threads * 100 assignments

    def test_not_deterministic(self):
        """Same inputs should NOT produce deterministic sequence."""
        strategy = RandomAssignment()
        experiment = _make_experiment()
        variants = _make_variants(n=10, equal_traffic=True)

        # Run twice with same inputs
        seq1 = [strategy.assign(experiment, variants, f"exec-{i}") for i in range(50)]
        seq2 = [strategy.assign(experiment, variants, f"exec-{i}") for i in range(50)]

        # With 10 variants and 50 samples, sequences should differ
        # (probability of exact match is astronomically low)
        assert seq1 != seq2, "Two runs produced identical sequences"
