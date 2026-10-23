"""Statistics for the report: bootstrap confidence intervals, the Wilcoxon signed-rank test, Holm.

Only the standard library is used, so the base cmeval install needs no numpy or scipy.

- Bootstrap: percentile intervals, 10,000 resamples, a fixed seed. Callers give values in a fixed
  order (sorted task ids), so the same inputs always give the same interval.
- Wilcoxon: gives the same p as scipy.stats.wilcoxon with its defaults (method "auto",
  zero_method "wilcox", correction False), as in scipy 1.13 to 1.17.
- Holm: the step-down correction for a family of tests.
"""

from __future__ import annotations

import functools
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

SEED = 20261023
RESAMPLES = 10_000
CONFIDENCE = 0.95
EXACT_MAX_N = 50  # exact test without ties or zeros up to this many pairs (as scipy)
PERMUTATION_MAX_N = 13  # exact test with ties or zeros up to this many pairs (as scipy)


def quantile(sorted_values: Sequence[float], q: float) -> float:
    """The q quantile of sorted values, with linear interpolation (the numpy default)."""
    position = q * (len(sorted_values) - 1)
    low = math.floor(position)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (position - low)


@functools.lru_cache(maxsize=None)
def resample_indexes(n: int, resamples: int, seed: int) -> tuple[tuple[int, ...], ...]:
    """The resamples (each n indexes drawn with replacement), the same for every metric of size n.

    A string seed is hashed with sha512, so the draws do not depend on PYTHONHASHSEED.
    """
    rng = random.Random(f"{seed}:{n}:{resamples}")
    population = range(n)
    return tuple(tuple(rng.choices(population, k=n)) for _ in range(resamples))


def bootstrap_ci(values: Sequence[float], *, resamples: int = RESAMPLES, seed: int = SEED,
                 confidence: float = CONFIDENCE) -> tuple[float, float] | None:
    """Percentile bootstrap interval of the mean. None for fewer than 2 values."""
    n = len(values)
    if n < 2:
        return None
    pick = list(values).__getitem__
    means = sorted(sum(map(pick, idx)) / n for idx in resample_indexes(n, resamples, seed))
    tail = (1 - confidence) / 2
    return quantile(means, tail), quantile(means, 1 - tail)


def differences(x: Sequence[float], y: Sequence[float]) -> list[float]:
    """x - y for each pair, rounded to 9 digits: scores have 6 digits, and plain subtraction
    would make float noise that looks like a difference (0.5 - 0.166667 vs. 0.333333)."""
    if len(x) != len(y):
        raise ValueError(f"paired values need the same length, got {len(x)} and {len(y)}")
    return [round(a - b, 9) for a, b in zip(x, y)]


def paired_bootstrap_ci(x: Sequence[float], y: Sequence[float], **kwargs) -> tuple[float, float] | None:
    """Bootstrap interval of the mean difference x - y. Resampling the differences is the same
    as resampling the pairs, because each pair is one task."""
    return bootstrap_ci(differences(x, y), **kwargs)


@dataclass(frozen=True)
class WilcoxonResult:
    n: int  # pairs, zeros included
    n_nonzero: int
    statistic: float | None  # min(sum of positive ranks, sum of negative ranks), as scipy
    p: float | None  # two-sided; None when there are no pairs
    method: str  # "exact", "normal", "all zero", or "no pairs"


def _average_ranks(values: Sequence[float]) -> tuple[list[float], list[int]]:
    """Ranks 1..m of the values (equal values share their average rank), and the tie group sizes."""
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    groups = []
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for position in range(i, j + 1):
            ranks[order[position]] = (i + j) / 2 + 1
        groups.append(j - i + 1)
        i = j + 1
    return ranks, groups


def wilcoxon(d: Sequence[float]) -> WilcoxonResult:
    """Two-sided Wilcoxon signed-rank test of paired differences d (zeros are dropped, as scipy)."""
    n = len(d)
    if n == 0:
        return WilcoxonResult(0, 0, None, None, "no pairs")
    nonzero = [v for v in d if v != 0]
    m = len(nonzero)
    if m == 0:
        return WilcoxonResult(n, 0, 0.0, 1.0, "all zero")
    ranks, groups = _average_ranks([abs(v) for v in nonzero])
    r_plus = sum(r for r, v in zip(ranks, nonzero) if v > 0)
    r_minus = m * (m + 1) / 2 - r_plus
    statistic = min(r_plus, r_minus)
    ties = any(size > 1 for size in groups)

    if (n <= EXACT_MAX_N and not ties and m == n) or n <= PERMUTATION_MAX_N:
        # Exact distribution of the positive rank sum over all 2^m sign patterns. Doubled
        # average ranks are whole numbers, so the sums can be counted in an array.
        weights = [round(2 * r) for r in ranks]
        counts = [0] * (sum(weights) + 1)
        counts[0] = 1
        top = 0
        for w in weights:
            for total in range(top, -1, -1):
                if counts[total]:
                    counts[total + w] += counts[total]
            top += w
        observed = round(2 * r_plus)
        low, high = sum(counts[: observed + 1]), sum(counts[observed:])
        p = min(1.0, 2 * min(low, high) / 2**m)
        return WilcoxonResult(n, m, statistic, p, "exact")

    mean = m * (m + 1) / 4
    variance = (m * (m + 1) * (2 * m + 1) - sum(t**3 - t for t in groups) / 2) / 24
    z = (r_plus - mean) / math.sqrt(variance)
    return WilcoxonResult(n, m, statistic, math.erfc(abs(z) / math.sqrt(2)), "normal")


def holm(pvalues: Sequence[float | None]) -> list[float]:
    """Holm-adjusted p-values, in the input order. A missing p counts as 1, so the family size
    stays the one that was fixed in advance."""
    ps = [1.0 if p is None else p for p in pvalues]
    family = len(ps)
    adjusted = [0.0] * family
    running = 0.0
    for step, index in enumerate(sorted(range(family), key=ps.__getitem__)):
        running = max(running, min(1.0, (family - step) * ps[index]))
        adjusted[index] = running
    return adjusted
