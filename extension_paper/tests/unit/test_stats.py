"""
Direct unit tests for amu_ext.stats.

Every experiment script (run_a1/a2/a4/a5, run_c1, run_c2) goes through
these helpers, so this module is exercised indirectly by the integration
smoke tests too -- but the error paths, the ``as_dict()`` serializers, and
the large-sample (n_discordant >= 25) branch of McNemar's test are not
naturally hit by any experiment's real data (the datasets here are small),
so they are tested directly here instead.
"""

from __future__ import annotations

import pytest

from amu_ext.stats import (
    PRF,
    BenchmarkResult,
    BootstrapCI,
    McNemarResult,
    benchmark_callable,
    bootstrap_ci,
    confusion_counts,
    mcnemar_test,
    precision_recall_f1,
)


class TestConfusionCountsAndPRF:
    def test_confusion_counts_all_four_quadrants(self) -> None:
        preds = [True, True, False, False]
        gt = [True, False, True, False]
        tp, fp, tn, fn = confusion_counts(preds, gt)
        assert (tp, fp, tn, fn) == (1, 1, 1, 1)

    def test_confusion_counts_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="same length"):
            confusion_counts([True, False], [True])

    def test_precision_recall_f1_zero_denominators_default_to_zero(self) -> None:
        # No positive predictions at all -> precision undefined -> 0.0;
        # no positive ground truth at all -> recall undefined -> 0.0.
        prf = precision_recall_f1([False, False], [False, False])
        assert prf.precision == 0.0
        assert prf.recall == 0.0
        assert prf.f1 == 0.0

    def test_prf_as_dict_rounds_and_names_fields(self) -> None:
        prf = PRF(tp=2, fp=1, tn=3, fn=1, precision=2 / 3, recall=2 / 3, f1=2 / 3)
        d = prf.as_dict()
        assert d["TP"] == 2 and d["FP"] == 1 and d["TN"] == 3 and d["FN"] == 1
        assert d["precision"] == round(2 / 3, 4)
        assert d["f1"] == round(2 / 3, 4)


class TestBootstrapCI:
    def test_empty_items_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            bootstrap_ci([], lambda r: 0.0, n_resamples=10)

    def test_deterministic_given_seed(self) -> None:
        items = [1, 2, 3, 4, 5]
        stat = lambda r: sum(r) / len(r)  # noqa: E731
        ci_a = bootstrap_ci(items, stat, n_resamples=200, seed=7)
        ci_b = bootstrap_ci(items, stat, n_resamples=200, seed=7)
        assert ci_a == ci_b

    def test_ci_bounds_are_ordered_and_contain_mean(self) -> None:
        items = list(range(20))
        stat = lambda r: sum(r) / len(r)  # noqa: E731
        ci = bootstrap_ci(items, stat, n_resamples=500, seed=1)
        assert ci.ci_lo <= ci.mean <= ci.ci_hi

    def test_bootstrap_ci_as_dict(self) -> None:
        ci = BootstrapCI(mean=0.5, ci_lo=0.3, ci_hi=0.7, confidence=0.95, n_resamples=1000)
        d = ci.as_dict()
        assert d == {"mean": 0.5, "ci_lo": 0.3, "ci_hi": 0.7, "confidence": 0.95, "n_resamples": 1000}


class TestMcNemar:
    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="same length"):
            mcnemar_test([True, False], [True])

    def test_no_discordant_pairs_returns_p_one(self) -> None:
        result = mcnemar_test([True, False, True], [True, False, True])
        assert result.n_discordant == 0
        assert result.p_value == 1.0
        assert result.exact is True

    def test_small_sample_uses_exact_binomial(self) -> None:
        # 3 discordant pairs -- well under the n=25 exact/chi-square cutoff.
        a = [True, True, True, False, False]
        b = [False, False, False, False, False]
        result = mcnemar_test(a, b)
        assert result.n_discordant == 3
        assert result.exact is True
        assert 0.0 <= result.p_value <= 1.0

    def test_large_sample_uses_chi_square_approximation(self) -> None:
        # Construct >=25 discordant pairs with a clear asymmetry (b >> c) so
        # this exercises the chi-square-with-Yates branch specifically.
        a = [True] * 30 + [False] * 5
        b = [False] * 30 + [False] * 5
        result = mcnemar_test(a, b)
        assert result.n_discordant == 30
        assert result.exact is False
        assert 0.0 <= result.p_value <= 1.0
        assert result.statistic > 0.0

    def test_mcnemar_result_as_dict(self) -> None:
        result = McNemarResult(n_discordant=5, b=4, c=1, statistic=1.8, p_value=0.1797, exact=True)
        d = result.as_dict()
        assert d["n_discordant"] == 5
        assert d["b_a_flags_not_b"] == 4
        assert d["c_b_flags_not_a"] == 1
        assert d["exact"] is True


class TestBenchmarkCallable:
    def test_benchmark_runs_and_reports_positive_timings(self) -> None:
        result = benchmark_callable(lambda: sum(range(10)), n_iter=25, n_warmup=5)
        assert result.n_iter == 25
        assert result.n_warmup == 5
        assert result.mean_us >= 0.0
        assert result.min_us <= result.median_us <= result.max_us

    def test_benchmark_result_as_dict(self) -> None:
        result = BenchmarkResult(
            mean_us=1.0, median_us=1.0, p95_us=1.5, sd_us=0.1, min_us=0.5, max_us=2.0, n_iter=100, n_warmup=10
        )
        d = result.as_dict()
        assert d["n_iter"] == 100
        assert d["n_warmup"] == 10
        assert d["mean_us"] == 1.0
