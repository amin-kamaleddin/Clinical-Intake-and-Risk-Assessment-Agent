"""Inter-rater reliability between two blinded LLM judges.

`record_score` and `flow_score` rest on one judge model and one pass. The
deterministic metrics and the fabrication count do not, which is exactly why
those two are the ones a reviewer will push on first.

The fix costs no new intakes: re-judge the SAME saved transcripts and records
with a second model from a different family, then report how well the two
agree. Two checkpoints of one model agreeing would show almost nothing, so the
second judge should not be another Gemini.

Two kinds of agreement, because the two metrics are different animals:

  RECORD  categorical verdicts (match / partial / missing / contradicted).
          Reported as raw agreement and Cohen's kappa. Kappa is the one to
          quote: these verdicts are dominated by `match`, so raw agreement is
          high even for two raters guessing independently, and kappa corrects
          for exactly that.

  FLOW    a bounded score on six anchor values. Reported as Spearman rank
          correlation (do the judges order the cases alike?), mean absolute
          difference (how far apart on the scale?) and exact-anchor agreement.
          Rank correlation matters more than exact equality: a systematic
          half-anchor offset between two judges leaves every comparison in the
          paper intact, whereas disagreement about WHICH intake was better
          does not.

No model calls. Everything is read from saved judge artifacts.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter

VERDICTS = ("match", "partial", "missing", "contradicted")


def cohens_kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Chance-corrected agreement for categorical labels.

    Returns None when undefined - fewer than two items, or one rater used a
    single label throughout, which makes expected agreement 1.0 and kappa 0/0.
    """
    if len(pairs) < 2:
        return None
    labels = sorted({label for pair in pairs for label in pair})
    n = len(pairs)
    observed = sum(1 for a, b in pairs if a == b) / n

    a_counts = Counter(a for a, _ in pairs)
    b_counts = Counter(b for _, b in pairs)
    expected = sum(
        (a_counts.get(label, 0) / n) * (b_counts.get(label, 0) / n)
        for label in labels
    )
    if math.isclose(expected, 1.0):
        return None
    return round((observed - expected) / (1 - expected), 4)


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Rank correlation, average ranks for ties (flow scores tie constantly)."""
    if len(xs) < 3:
        return None

    def rank(values):
        order = sorted(range(len(values)), key=lambda i: values[i])
        ranks = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            shared = (i + j) / 2 + 1
            for k in range(i, j + 1):
                ranks[order[k]] = shared
            i = j + 1
        return ranks

    rx, ry = rank(xs), rank(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(
        sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)
    )
    return round(num / den, 4) if den else None


def flow_agreement(paired: list[tuple[float, float]]) -> dict:
    """Agreement between two judges' flow scores on the same transcripts."""
    if not paired:
        return {"cases": 0}
    xs = [a for a, _ in paired]
    ys = [b for _, b in paired]
    diffs = [b - a for a, b in paired]
    return {
        "cases": len(paired),
        "judge_a_mean": round(statistics.mean(xs), 4),
        "judge_b_mean": round(statistics.mean(ys), 4),
        # Signed, so a systematic leniency difference is visible rather than
        # hidden inside a mean absolute value.
        "mean_signed_difference": round(statistics.mean(diffs), 4),
        "mean_absolute_difference": round(
            statistics.mean(abs(d) for d in diffs), 4
        ),
        "max_absolute_difference": round(max(abs(d) for d in diffs), 4),
        "spearman": spearman(xs, ys),
        "exact_anchor_agreement": round(
            sum(1 for a, b in paired if math.isclose(a, b)) / len(paired), 4
        ),
        "within_one_anchor": round(
            sum(1 for a, b in paired if abs(a - b) <= 0.15 + 1e-9) / len(paired), 4
        ),
    }


def record_agreement(paired: list[tuple[str, str]]) -> dict:
    """Agreement between two judges' categorical field verdicts."""
    if not paired:
        return {"fields": 0}
    agreed = sum(1 for a, b in paired if a == b)
    confusion: dict = {}
    for a, b in paired:
        confusion.setdefault(a, Counter())[b] += 1
    return {
        "fields": len(paired),
        "raw_agreement": round(agreed / len(paired), 4),
        # Quote this one. These verdicts are ~90% `match`, so raw agreement
        # stays high even for independent guessing.
        "cohens_kappa": cohens_kappa(paired),
        "judge_a_distribution": dict(Counter(a for a, _ in paired)),
        "judge_b_distribution": dict(Counter(b for _, b in paired)),
        "confusion": {a: dict(row) for a, row in confusion.items()},
    }


def interpret_kappa(kappa: float | None) -> str:
    """Landis & Koch bands. Reported as a label, never as a pass/fail."""
    if kappa is None:
        return "undefined"
    for threshold, label in (
        (0.81, "almost perfect"), (0.61, "substantial"), (0.41, "moderate"),
        (0.21, "fair"), (0.0, "slight"),
    ):
        if kappa >= threshold:
            return label
    return "poor (worse than chance)"


def format_summary(report: dict) -> str:
    lines = [
        "INTER-RATER RELIABILITY",
        f"  judge A: {report.get('judge_a_model')}",
        f"  judge B: {report.get('judge_b_model')}",
        "",
    ]
    for system, block in (report.get("systems") or {}).items():
        rec = block.get("record") or {}
        flow = block.get("flow") or {}
        kappa = rec.get("cohens_kappa")
        lines += [
            f"  {system}",
            f"    record verdicts: {rec.get('fields', 0)} fields, "
            f"raw {rec.get('raw_agreement')}, kappa {kappa} "
            f"({interpret_kappa(kappa)})",
            f"    flow: {flow.get('cases', 0)} cases, "
            f"spearman {flow.get('spearman')}, "
            f"mean abs diff {flow.get('mean_absolute_difference')}, "
            f"signed {flow.get('mean_signed_difference')}",
        ]
    return "\n".join(lines)
