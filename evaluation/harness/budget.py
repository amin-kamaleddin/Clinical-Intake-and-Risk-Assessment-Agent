
from __future__ import annotations

from statistics import mean, median


def _turn_text(turn) -> str:
    if isinstance(turn, dict):
        return str(turn.get("message") or turn.get("content") or "")
    return str(turn or "")


def _speaker(turn) -> str:
    if isinstance(turn, dict):
        return str(turn.get("speaker") or turn.get("role") or "").upper()
    return ""


def measure(conversation, elapsed_seconds: float | None = None) -> dict:

    turns = list(conversation or [])
    system_turns = [t for t in turns if _speaker(t) not in ("PATIENT", "USER")]
    patient_turns = [t for t in turns if _speaker(t) in ("PATIENT", "USER")]

    system_words = sum(len(_turn_text(t).split()) for t in system_turns)
    patient_words = sum(len(_turn_text(t).split()) for t in patient_turns)

    return {
        "total_turns": len(turns),
        "system_turns": len(system_turns),
        "patient_turns": len(patient_turns),
        "system_words": system_words,
        "patient_words": patient_words,
        "total_words": system_words + patient_words,
        "mean_system_turn_words": (
            round(system_words / len(system_turns), 1) if system_turns else None
        ),
        "elapsed_seconds": (
            round(elapsed_seconds, 1) if elapsed_seconds is not None else None
        ),
    }


def summarize(budgets: list[dict]) -> dict:
    """Aggregate per-case budgets, reporting median alongside mean.

    Median as well as mean because a single runaway case (a section that hit its
    turn cap) skews the mean and would misrepresent the typical interaction.
    """
    usable = [b for b in budgets if b]
    if not usable:
        return {"cases": 0}

    def stat(key, fn):
        values = [b[key] for b in usable if b.get(key) is not None]
        return round(fn(values), 1) if values else None

    return {
        "cases": len(usable),
        "median_total_turns": stat("total_turns", median),
        "mean_total_turns": stat("total_turns", mean),
        "max_total_turns": stat("total_turns", max),
        "median_system_turns": stat("system_turns", median),
        "median_total_words": stat("total_words", median),
        "mean_total_words": stat("total_words", mean),
        "median_elapsed_seconds": stat("elapsed_seconds", median),
        "total_elapsed_seconds": stat("elapsed_seconds", sum),
    }


def compare(summaries: dict[str, dict]) -> dict:
    """Turn/word ratios between systems, relative to the cheapest.

    A ratio far from 1.0 is the warning: the arms did not have equivalent
    interaction budgets, so any completeness or flow difference is confounded
    with effort and must be reported as such.
    """
    turns = {s: v.get("median_total_turns") for s, v in summaries.items()
             if v.get("median_total_turns")}
    words = {s: v.get("median_total_words") for s, v in summaries.items()
             if v.get("median_total_words")}
    if not turns:
        return {}

    cheapest_turns = min(turns, key=turns.get)
    return {
        "reference_system": cheapest_turns,
        "turn_ratio_vs_reference": {
            s: round(v / turns[cheapest_turns], 2) for s, v in turns.items()
        },
        "word_ratio_vs_reference": {
            s: round(v / words[min(words, key=words.get)], 2) for s, v in words.items()
        } if words else {},
        "interpretation": (
            "A ratio far from 1.0 means the arms did not have equivalent "
            "interaction budgets. Completeness and flow differences are then "
            "confounded with effort: report as a system comparison, not an "
            "architecture ablation, or run a budget-matched analysis."
        ),
    }


def format_summary(summaries: dict[str, dict], comparison: dict) -> str:
    lines = [
        "INTERACTION BUDGET (transcript-derived; equal budgets are not enforced)",
        f"{'system':>12} | {'median turns':>13} | {'median words':>13} | "
        f"{'median seconds':>15} | {'turn ratio':>11}",
        "-" * 78,
    ]
    ratios = comparison.get("turn_ratio_vs_reference", {})
    for system, summary in summaries.items():
        lines.append(
            f"{system:>12} | {str(summary.get('median_total_turns')):>13} | "
            f"{str(summary.get('median_total_words')):>13} | "
            f"{str(summary.get('median_elapsed_seconds')):>15} | "
            f"{str(ratios.get(system)):>11}"
        )
    if ratios and max(ratios.values()) >= 1.2:
        lines.append("")
        lines.append("  WARNING: interaction budgets differ by 20% or more.")
        lines.append("  Completeness and flow differences are confounded with effort.")
    return "\n".join(lines)
