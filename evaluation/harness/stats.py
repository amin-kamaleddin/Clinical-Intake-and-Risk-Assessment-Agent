

from __future__ import annotations

import random
from statistics import mean, median
from typing import Callable, Sequence

# Fixed so a reported interval is reproducible. Resampling noise should not
# change the number between two runs of the analysis on identical data.
BOOTSTRAP_SEED = 20260804
BOOTSTRAP_RESAMPLES = 10_000
CONFIDENCE = 0.95


def _percentile(sorted_values: Sequence[float], fraction: float) -> float:
    """Linear-interpolated percentile of an already-sorted sequence."""
    if not sorted_values:
        raise ValueError("empty sequence")
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = fraction * (len(sorted_values) - 1)
    low = int(position)
    high = min(low + 1, len(sorted_values) - 1)
    weight = position - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


def _clean(groups: dict[str, list]) -> dict[str, list[float]]:
    """Drop Nones and empty scenarios; a metric may be absent for a case."""
    cleaned = {}
    for key, values in groups.items():
        usable = [float(v) for v in values if v is not None]
        if usable:
            cleaned[key] = usable
    return cleaned


def cluster_bootstrap(
    groups: dict[str, list],
    statistic: Callable[[list[float]], float] = mean,
    resamples: int = BOOTSTRAP_RESAMPLES,
    confidence: float = CONFIDENCE,
    seed: int = BOOTSTRAP_SEED,
) -> dict:
    """Mean over scenarios with a clustered 95% CI.

    ``groups`` maps a cluster id (scenario id) to that scenario's observations
    (one per repetition). The point estimate is the mean of per-scenario means,
    so a scenario that happened to run more repetitions does not get more weight.
    """
    groups = _clean(groups)
    if not groups:
        return {"estimate": None, "ci_low": None, "ci_high": None,
                "scenarios": 0, "observations": 0, "repetitions_per_scenario": None}

    keys = list(groups)
    observations = sum(len(v) for v in groups.values())
    per_scenario = [statistic(groups[k]) for k in keys]
    estimate = mean(per_scenario)

    # A single scenario, or one observation each, cannot support an interval.
    if len(keys) < 2 and observations < 2:
        return {"estimate": round(estimate, 4), "ci_low": None, "ci_high": None,
                "scenarios": len(keys), "observations": observations,
                "repetitions_per_scenario": round(observations / len(keys), 2),
                "note": "too few observations for an interval"}

    rng = random.Random(seed)
    draws = []
    for _ in range(resamples):
        drawn_keys = [rng.choice(keys) for _ in keys]          # resample scenarios
        drawn = []
        for key in drawn_keys:
            values = groups[key]
            # resample repetitions within the drawn scenario
            drawn.append(statistic([rng.choice(values) for _ in values]))
        draws.append(mean(drawn))
    draws.sort()

    tail = (1 - confidence) / 2
    return {
        "estimate": round(estimate, 4),
        "ci_low": round(_percentile(draws, tail), 4),
        "ci_high": round(_percentile(draws, 1 - tail), 4),
        "scenarios": len(keys),
        "observations": observations,
        "repetitions_per_scenario": round(observations / len(keys), 2),
        "confidence": confidence,
    }


def paired_bootstrap_difference(
    groups_a: dict[str, list],
    groups_b: dict[str, list],
    statistic: Callable[[list[float]], float] = mean,
    resamples: int = BOOTSTRAP_RESAMPLES,
    confidence: float = CONFIDENCE,
    seed: int = BOOTSTRAP_SEED,
) -> dict:
    """CI for (A - B) on the scenarios both systems completed.

    Resamples the same scenarios for both systems within each draw, so scenario
    difficulty cancels. ``excludes_zero`` is the only basis on which to claim
    one system beats another; two overlapping individual intervals do NOT imply
    the difference is indistinguishable from zero.
    """
    groups_a, groups_b = _clean(groups_a), _clean(groups_b)
    shared = sorted(set(groups_a) & set(groups_b))
    if len(shared) < 2:
        return {"difference": None, "ci_low": None, "ci_high": None,
                "paired_scenarios": len(shared), "excludes_zero": None,
                "note": "too few shared scenarios for a paired interval"}

    per_scenario = [statistic(groups_a[k]) - statistic(groups_b[k]) for k in shared]
    difference = mean(per_scenario)

    rng = random.Random(seed)
    draws = []
    for _ in range(resamples):
        drawn_keys = [rng.choice(shared) for _ in shared]
        drawn = []
        for key in drawn_keys:
            a_values, b_values = groups_a[key], groups_b[key]
            a_stat = statistic([rng.choice(a_values) for _ in a_values])
            b_stat = statistic([rng.choice(b_values) for _ in b_values])
            drawn.append(a_stat - b_stat)
        draws.append(mean(drawn))
    draws.sort()

    tail = (1 - confidence) / 2
    low = round(_percentile(draws, tail), 4)
    high = round(_percentile(draws, 1 - tail), 4)
    return {
        "difference": round(difference, 4),
        "ci_low": low,
        "ci_high": high,
        "paired_scenarios": len(shared),
        # The claim test. If this is False, say the systems are comparable.
        "excludes_zero": low > 0 or high < 0,
        "confidence": confidence,
    }


def wilson_interval(successes: int, trials: int, confidence: float = CONFIDENCE) -> dict:
    """CI for a proportion, e.g. safety sensitivity.

    Wilson rather than normal: with 5 positive cases and 5 successes, the normal
    interval is [1.0, 1.0], which asserts certainty a 5-case sample cannot
    support. Wilson stays inside [0, 1] and keeps a sane width at the boundary.
    """
    if trials <= 0:
        return {"estimate": None, "ci_low": None, "ci_high": None, "trials": 0}

    z = 1.959964 if abs(confidence - 0.95) < 1e-9 else 1.959964
    proportion = successes / trials
    denominator = 1 + z * z / trials
    centre = (proportion + z * z / (2 * trials)) / denominator
    spread = (
        z * ((proportion * (1 - proportion) / trials
              + z * z / (4 * trials * trials)) ** 0.5) / denominator
    )
    return {
        "estimate": round(proportion, 4),
        "ci_low": round(max(0.0, centre - spread), 4),
        "ci_high": round(min(1.0, centre + spread), 4),
        "successes": successes,
        "trials": trials,
        "method": "wilson",
        "confidence": confidence,
    }


def variability(groups: dict[str, list]) -> dict:
    """How much a system varies on the SAME scenario across repetitions.

    Reported because it bounds what any single-run comparison can mean: if the
    within-scenario range is wider than the gap between two systems, that gap
    is not a result. This is the number that justifies running repetitions at
    all, so it belongs in the report rather than in a footnote.
    """
    groups = _clean(groups)
    spreads = [max(v) - min(v) for v in groups.values() if len(v) > 1]
    if not spreads:
        return {"median_within_scenario_range": None, "max_within_scenario_range": None,
                "scenarios_with_repetitions": 0}
    return {
        "median_within_scenario_range": round(median(spreads), 4),
        "max_within_scenario_range": round(max(spreads), 4),
        "scenarios_with_repetitions": len(spreads),
    }


def format_ci(result: dict, digits: int = 3) -> str:
    """``0.933 [0.901, 0.958]`` - or the bare estimate when no interval exists."""
    if not result or result.get("estimate") is None:
        return "n/a"
    estimate = f"{result['estimate']:.{digits}f}"
    if result.get("ci_low") is None:
        return estimate
    return f"{estimate} [{result['ci_low']:.{digits}f}, {result['ci_high']:.{digits}f}]"


def format_difference(result: dict, digits: int = 3) -> str:
    if not result or result.get("difference") is None:
        return "n/a"
    text = (f"{result['difference']:+.{digits}f} "
            f"[{result['ci_low']:+.{digits}f}, {result['ci_high']:+.{digits}f}]")
    return text + ("  *" if result.get("excludes_zero") else "  (n.s.)")
