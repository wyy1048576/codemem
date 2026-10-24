import random
import statistics

import pytest

from cmeval.metrics.stats import (bootstrap_ci, differences, holm, paired_bootstrap_ci, quantile, wilcoxon)

# p-values from scipy.stats.wilcoxon(d) with its defaults, scipy 1.17.1 (computed once, outside
# the repo). The cases cover each of scipy's methods: exact, exact with ties or zeros (n <= 13),
# and the normal approximation (with zeros, with ties, n > 50).
SCIPY_CASES = [
    ([-0.052334, -0.398302, 0.601869, -0.555127, 0.371764, 0.031378, -0.584002, 0.314871, -0.625009, 0.167291, -0.560289, -0.518574, 0.149038, 0.953704, -0.452396, -0.253522, 0.554866, 1.195418, 0.454206, 0.093361],
     0.9272785186767578),  # no ties, n=20
    ([1, -1, 2, 2, -0.5, 3, 1, 2],
     0.0625),  # ties, n=8
    ([0.0, 0.0, 0.0, 0.0, 1.15251, -0.706835, 0.916937, -0.220781, -0.51149, -0.564416, -0.183036, 0.832253, -0.438547, 0.3632, 0.477827, -0.055205, 0.295489, -0.674422, -0.680798, -0.388083],
     0.7563688628810696),  # zeros, n=20
    ([-0.5, 0.5, -1, 2, 1, -1, 0.5, -1, 1, 1, 0, 2, 0, -0.5, 2, 0, 0, 0.5, 1, 0.5, -1, 1, -0.5, -1, 1, 0.5, 0, 0, 0.5, -1, 0, 2, 1, 0, -1, -1, 0, -0.5, 0, 2],
     0.16284662372586256),  # zeros and ties, n=40
    ([0.266152, 0.728188, 0.786707, -0.169755, -0.149643, 0.14335, 0.743784, -0.712474, -0.662808, -0.310121, 0.544084, -0.72, 0.612319, -0.230785, 0.305892, 0.512474, 0.041282, 0.583256, 0.924081, -0.155989, 1.031297, -0.139072, 0.371839, 0.137386, -0.413584, -0.275136, 0.626727, -0.054205, 0.983632, 0.143013, -0.517267, -0.046711, -0.294322, -0.576148, 0.011043, 0.250439, 0.562793, 1.122934, 0.515446, -0.089117, -0.388497, -0.684031, -0.547403, 0.467033, -0.825874, 0.812187, -0.485314, -0.286139, -0.558647, 0.219182, 0.369625, -0.212777, -0.599017, 0.868404, 1.050448, 0.459933, 0.629569, 0.063287, 0.891959, 1.053772],
     0.0701479201609403),  # no ties, n=60
    ([-0.75, 0.333333333, -0.666666667, -0.166666667, -0.666666667, 0, -0.166666667, 0.333333333, -0.5, 0.5, -1, 0.5, -0.666666667, 0.5, -1, -0.5, -0.75, -0.2, -1, -1, 0.05, 0.5, 0.25, 0, 0.0, 0.05, -0.5, -1, 0.5, 0.05, -0.166666667, 0.5, 0.5, -0.5, 0.25, -0.5, 0.133333333, -1, -0.5, -0.666666667, 0.133333333, 0.333333333, 0.133333333, 0.0, 0, 1, -0.2, -0.5, 0.3, -0.666666667],
     0.026275624057731935),  # mrr-like, n=50
]


@pytest.mark.parametrize("d, expected", SCIPY_CASES)
def test_wilcoxon_matches_scipy(d, expected):
    assert wilcoxon(d).p == pytest.approx(expected, rel=1e-9)


def test_wilcoxon_by_hand():
    # 5 positive differences: only 1 of the 32 sign patterns is as extreme on each side.
    result = wilcoxon([1, 2, 3, 4, 5])
    assert (result.p, result.method, result.statistic) == (0.0625, "exact", 0.0)
    assert wilcoxon([-1, -2, -3, -4, -5]).p == 0.0625
    # Zeros are dropped; with 7 pairs (n <= 13) the test is still exact.
    result = wilcoxon([0, 0, 1, 2, 3, 4, 5])
    assert (result.n, result.n_nonzero, result.p, result.method) == (7, 5, 0.0625, "exact")


def test_wilcoxon_edge_cases():
    assert wilcoxon([]).p is None and wilcoxon([]).method == "no pairs"
    assert (wilcoxon([0, 0, 0]).p, wilcoxon([0, 0, 0]).method) == (1.0, "all zero")
    assert wilcoxon([0.5]).p == 1.0  # one pair can never be significant
    assert wilcoxon([0.0] * 40 + [1.0] * 30).method == "normal"  # zeros and n > 13


def test_differences_remove_float_noise():
    assert differences([0.5], [0.166667]) == [0.333333]
    with pytest.raises(ValueError, match="same length"):
        differences([1], [1, 2])


def test_holm():
    assert holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert holm([0.01, None]) == [0.02, 1.0]  # a missing p counts as 1: the family size stays fixed
    assert holm([0.4, 0.5]) == [0.8, 0.8]  # step-down: never smaller than an earlier one
    assert holm([0.9, 0.9]) == [1.0, 1.0]


def test_quantile_is_linear_interpolation():
    assert quantile([1, 2, 3, 4], 0.5) == 2.5
    assert quantile([0, 10], 0.25) == 2.5
    data = sorted(random.Random(3).random() for _ in range(37))
    cuts = statistics.quantiles(data, n=40, method="inclusive")
    assert quantile(data, 0.025) == pytest.approx(cuts[0]) and quantile(data, 0.975) == pytest.approx(cuts[-1])


def test_bootstrap_ci():
    assert bootstrap_ci([0.7] * 10, resamples=200) == pytest.approx((0.7, 0.7))
    assert bootstrap_ci([1.0]) is None and bootstrap_ci([]) is None
    values = [0.0] * 25 + [1.0] * 25
    lo, hi = bootstrap_ci(values)
    assert lo < 0.5 < hi and lo == pytest.approx(0.36, abs=0.03) and hi == pytest.approx(0.64, abs=0.03)
    assert bootstrap_ci(values) == (lo, hi)  # fixed seed: the same interval every time
    rng = random.Random(5)
    smooth = [rng.random() for _ in range(30)]
    assert bootstrap_ci(smooth, resamples=500) != bootstrap_ci(smooth, resamples=500, seed=1)


def test_paired_bootstrap_ci():
    x, y = [1.0, 0.5, 1.0, 0.25, 1.0], [0.5, 0.5, 0.0, 0.25, 0.5]
    lo, hi = paired_bootstrap_ci(x, y, resamples=500)
    assert lo <= statistics.mean(differences(x, y)) <= hi
    assert paired_bootstrap_ci(x, x, resamples=500) == (0.0, 0.0)
