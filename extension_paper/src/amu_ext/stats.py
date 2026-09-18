"""
Shared statistical helpers for the extension-paper experiments.

Every experiment in ``experiments/`` that reports precision/recall/F1,
confidence intervals, or a significance test goes through this module, so
the methodology is identical (and auditable in one place) across Group A's
detector evaluation, Group B's materialization sweep, and Group C's
reproducibility checks.

Methodology notes
------------------
- Bootstrap confidence intervals use the percentile method: resample the
  paired observations with replacement ``n_resamples`` times, recompute the
  statistic on each resample, and report the 2.5th/97.5th percentiles as the
  95% CI. This mirrors ``fuzzy_experiment.py``'s existing (unextended)
  bootstrap helper in the root repo -- we generalize it rather than
  reinvent it.
- McNemar's test is the standard paired test for comparing two binary
  classifiers on the *same* items: it only uses the discordant pairs (cases
  where the two detectors disagree) and asks whether the direction of
  disagreement is symmetric. We use the exact binomial form when the number
  of discordant pairs is small (<25, the usual continuity-correction
  threshold) and the chi-square form with continuity correction otherwise.
"""

from __future__ import annotations

import math
import random
import statistics
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple

__all__ = [
    "PRF",
    "precision_recall_f1",
    "confusion_counts",
    "BootstrapCI",
    "bootstrap_ci",
    "McNemarResult",
    "mcnemar_test",
    "BenchmarkResult",
    "benchmark_callable",
]


@dataclass(frozen=True)
class PRF:
    """Precision / recall / F1 plus the underlying confusion counts."""

    tp: int
    fp: int
    tn: int
    fn: int
    precision: float
    recall: float
    f1: float

    def as_dict(self) -> Dict[str, float]:
        return {
            "TP": self.tp,
            "FP": self.fp,
            "TN": self.tn,
            "FN": self.fn,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
        }


def confusion_counts(predictions: Sequence[bool], ground_truth: Sequence[bool]) -> Tuple[int, int, int, int]:
    """Return (tp, fp, tn, fn) for parallel prediction/ground-truth sequences.

    Args:
        predictions: detector output per item (True = flagged as conflict).
        ground_truth: ground-truth label per item (True = is a real conflict).

    Returns:
        (tp, fp, tn, fn) counts.

    Raises:
        ValueError: if the two sequences have different lengths.
    """
    if len(predictions) != len(ground_truth):
        raise ValueError(
            f"predictions and ground_truth must be the same length "
            f"(got {len(predictions)} vs {len(ground_truth)})"
        )
    tp = fp = tn = fn = 0
    for pred, gt in zip(predictions, ground_truth):
        if pred and gt:
            tp += 1
        elif pred and not gt:
            fp += 1
        elif not pred and gt:
            fn += 1
        else:
            tn += 1
    return tp, fp, tn, fn


def precision_recall_f1(predictions: Sequence[bool], ground_truth: Sequence[bool]) -> PRF:
    """Compute precision, recall, and F1 for a binary detector.

    Precision/recall/F1 are defined 0.0 when their denominator is zero
    (no positive predictions / no positive ground truth), matching the
    convention already used by ``fuzzy_experiment.py`` in the root repo.

    Args:
        predictions: detector output per item.
        ground_truth: ground-truth label per item.

    Returns:
        A :class:`PRF` with counts and metrics.
    """
    tp, fp, tn, fn = confusion_counts(predictions, ground_truth)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return PRF(tp=tp, fp=fp, tn=tn, fn=fn, precision=precision, recall=recall, f1=f1)


@dataclass(frozen=True)
class BootstrapCI:
    """A bootstrapped point estimate with a percentile confidence interval."""

    mean: float
    ci_lo: float
    ci_hi: float
    confidence: float
    n_resamples: int

    def as_dict(self) -> Dict[str, float]:
        return {
            "mean": round(self.mean, 4),
            "ci_lo": round(self.ci_lo, 4),
            "ci_hi": round(self.ci_hi, 4),
            "confidence": self.confidence,
            "n_resamples": self.n_resamples,
        }


def bootstrap_ci(
    items: Sequence[object],
    statistic_fn: Callable[[Sequence[object]], float],
    *,
    n_resamples: int = 10_000,
    confidence: float = 0.95,
    seed: int = 42,
) -> BootstrapCI:
    """Percentile-method bootstrap confidence interval for an arbitrary statistic.

    Resamples ``items`` with replacement ``n_resamples`` times (same size as
    the original sample each time), applies ``statistic_fn`` to each
    resample, and reports the mean of those resample statistics plus the
    ``confidence`` percentile interval.

    Args:
        items: the observations to resample (e.g. one row per labeled pair).
        statistic_fn: function mapping a resampled sequence of items to a
            single float (e.g. "compute F1 of detector D on this resample").
        n_resamples: number of bootstrap resamples (default 10,000, matching
            the paper's existing convention).
        confidence: confidence level for the interval (default 0.95).
        seed: RNG seed, so results are exactly reproducible.

    Returns:
        A :class:`BootstrapCI`.

    Raises:
        ValueError: if ``items`` is empty.
    """
    if not items:
        raise ValueError("cannot bootstrap an empty sample")
    rng = random.Random(seed)
    n = len(items)
    values: List[float] = []
    for _ in range(n_resamples):
        resample = [items[rng.randrange(n)] for _ in range(n)]
        values.append(statistic_fn(resample))
    values.sort()
    alpha = 1.0 - confidence
    lo_idx = int((alpha / 2) * n_resamples)
    hi_idx = min(n_resamples - 1, int((1 - alpha / 2) * n_resamples))
    return BootstrapCI(
        mean=statistics.mean(values),
        ci_lo=values[lo_idx],
        ci_hi=values[hi_idx],
        confidence=confidence,
        n_resamples=n_resamples,
    )


@dataclass(frozen=True)
class McNemarResult:
    """Result of a paired McNemar test between two binary classifiers."""

    n_discordant: int
    b: int  # count: detector_a correct alone is not what b/c mean; see mcnemar_test docstring
    c: int
    statistic: float
    p_value: float
    exact: bool

    def as_dict(self) -> Dict[str, float]:
        return {
            "n_discordant": self.n_discordant,
            "b_a_flags_not_b": self.b,
            "c_b_flags_not_a": self.c,
            "statistic": round(self.statistic, 4),
            "p_value": round(self.p_value, 6),
            "exact": self.exact,
        }


def _binom_cdf_two_sided_p(b: int, c: int) -> float:
    """Exact two-sided McNemar p-value via the binomial distribution.

    Under the null (marginal homogeneity), b ~ Binomial(n=b+c, p=0.5).
    The two-sided exact p-value is 2 * min(P(X <= min(b,c)), P(X >= max(b,c))),
    capped at 1.0 -- the standard exact-McNemar formulation.
    """
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)

    def _log_binom_pmf(i: int) -> float:
        return (
            math.lgamma(n + 1)
            - math.lgamma(i + 1)
            - math.lgamma(n - i + 1)
            + i * math.log(0.5)
            + (n - i) * math.log(0.5)
        )

    p_le_k = sum(math.exp(_log_binom_pmf(i)) for i in range(0, k + 1))
    p_value = min(1.0, 2 * p_le_k)
    return p_value


def mcnemar_test(predictions_a: Sequence[bool], predictions_b: Sequence[bool]) -> McNemarResult:
    """Paired McNemar test comparing two detectors on the same items.

    Uses only the *discordant* pairs -- items where the two detectors
    disagree -- and tests whether disagreements favor one detector over the
    other more than chance would predict (i.e. whether the two detectors'
    error patterns are asymmetric).

    ``b`` = number of items where detector A flags a conflict and detector B
    does not. ``c`` = number of items where detector B flags a conflict and
    detector A does not. Ground truth is irrelevant to this test by design:
    McNemar compares the two *predictions* directly, not their accuracy.

    When ``b + c < 25`` (the usual small-sample threshold), the exact
    binomial two-sided test is used; otherwise the chi-square approximation
    with Yates' continuity correction is used.

    Args:
        predictions_a: detector A's binary predictions.
        predictions_b: detector B's binary predictions, same order/length.

    Returns:
        A :class:`McNemarResult`.

    Raises:
        ValueError: if the sequences have different lengths.
    """
    if len(predictions_a) != len(predictions_b):
        raise ValueError("predictions_a and predictions_b must be the same length")

    b = sum(1 for a, bb in zip(predictions_a, predictions_b) if a and not bb)
    c = sum(1 for a, bb in zip(predictions_a, predictions_b) if bb and not a)
    n_discordant = b + c

    if n_discordant == 0:
        return McNemarResult(n_discordant=0, b=0, c=0, statistic=0.0, p_value=1.0, exact=True)

    if n_discordant < 25:
        p_value = _binom_cdf_two_sided_p(b, c)
        # Report the exact-test statistic as min(b, c) by convention.
        statistic = float(min(b, c))
        return McNemarResult(
            n_discordant=n_discordant, b=b, c=c, statistic=statistic, p_value=p_value, exact=True
        )

    # Chi-square approximation with Yates' continuity correction.
    statistic = ((abs(b - c) - 1) ** 2) / n_discordant
    # Survival function of chi-square with 1 df, computed via the
    # regularized upper incomplete gamma function (avoids a scipy
    # dependency for this one call): P(X > x) for X ~ chi2(1).
    p_value = math.erfc(math.sqrt(statistic / 2.0))
    return McNemarResult(
        n_discordant=n_discordant, b=b, c=c, statistic=statistic, p_value=min(1.0, p_value), exact=False
    )


@dataclass(frozen=True)
class BenchmarkResult:
    """Timing statistics for a benchmarked callable, in microseconds."""

    mean_us: float
    median_us: float
    p95_us: float
    sd_us: float
    min_us: float
    max_us: float
    n_iter: int
    n_warmup: int

    def as_dict(self) -> Dict[str, float]:
        return {
            "mean_us": round(self.mean_us, 4),
            "median_us": round(self.median_us, 4),
            "p95_us": round(self.p95_us, 4),
            "sd_us": round(self.sd_us, 4),
            "min_us": round(self.min_us, 4),
            "max_us": round(self.max_us, 4),
            "n_iter": self.n_iter,
            "n_warmup": self.n_warmup,
        }


def benchmark_callable(
    fn: Callable[[], object], *, n_iter: int = 2000, n_warmup: int = 200
) -> BenchmarkResult:
    """Time ``fn()`` repeatedly with ``time.perf_counter()``, microsecond scale.

    Extends the root repo's ``benchmark_runtime.py`` convention (sequential
    ``time.perf_counter()`` timing, N iterations, microsecond units, no
    external profiler dependency) with two additions the Group A5 runtime
    benchmark explicitly asks for: a discarded warm-up phase (so import-time
    caching, attribute-lookup warm-up, and any first-call JIT-adjacent
    effects in CPython's bytecode cache don't bias the measured
    distribution) and reported percentiles (median, p95) alongside
    mean/sd/min/max, which better characterize tail latency than mean+sd
    alone for a governance-path operation.

    Args:
        fn: a zero-argument callable to time. Any argument binding (e.g. via
            a lambda or ``functools.partial``) should happen before this
            call, so the timed region is only the operation under test.
        n_iter: number of *timed* iterations (default 2000, matching
            ``benchmark_runtime.py``'s ``N_ITER``).
        n_warmup: number of untimed warm-up calls run (and discarded)
            immediately before timing begins.

    Returns:
        A :class:`BenchmarkResult`.
    """
    for _ in range(n_warmup):
        fn()

    times: List[float] = []
    for _ in range(n_iter):
        t0 = time.perf_counter()
        fn()
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1e6)  # seconds -> microseconds

    times.sort()
    p95_idx = min(n_iter - 1, int(0.95 * n_iter))
    return BenchmarkResult(
        mean_us=statistics.mean(times),
        median_us=statistics.median(times),
        p95_us=times[p95_idx],
        sd_us=statistics.pstdev(times),
        min_us=times[0],
        max_us=times[-1],
        n_iter=n_iter,
        n_warmup=n_warmup,
    )
