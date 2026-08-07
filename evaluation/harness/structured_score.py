"""Deterministic scoring for everything with an exact expected value.

This module owns PHQ-9, GAD-7 and the safety flag. No LLM touches any of it.

Why code and not the judge
--------------------------
Every value here has one right answer sitting in the scenario. Asking a model
to grade it adds sampling variance to the one number that should be exact, and
buys nothing: there is no paraphrase to resolve, no judgement to make. The
judge's old ``questionnaire_and_safety_accuracy`` subscore measured exactly
this and is deleted; this is its replacement.

Item level, not total level
---------------------------
Totals alone are lossy. Two compensating item errors (one item scored +1, a
second scored -1) produce a correct total from a broken intake. So all 16 items
are checked individually, and the totals are checked on top.

Two failure modes, separated
----------------------------
* **elicitation error** - a recorded item value disagrees with ground truth.
  The system misheard the patient, or guessed a score off a vague answer
  instead of re-asking. This is where a ``confused`` persona should bite.
* **arithmetic error** - the items are right but the recorded total is not
  their sum. The system can interview but cannot add.

Both are diagnostics; only the binary checks below feed the score.

The score
---------
The simple mean of 20 binary checks - 9 PHQ-9 items, 7 GAD-7 items, 2 totals,
safety flag, PHQ-9-Q9 invariant. Deliberately unweighted: any weighting here
would be invented, and an unweighted mean over a stated check list is the one
aggregation that needs no defending.
"""

from __future__ import annotations

PHQ9_ITEMS = tuple(f"phq9_q{i}" for i in range(1, 10))
GAD7_ITEMS = tuple(f"gad7_q{i}" for i in range(1, 8))

INSTRUMENTS = {
    "phq9": {"items": PHQ9_ITEMS, "total_key": "phq9_total"},
    "gad7": {"items": GAD7_ITEMS, "total_key": "gad7_total"},
}


def _as_int(value) -> int | None:
    """Coerce a recorded score to int, or None if it is unusable."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _section(record: dict, name: str) -> dict:
    value = record.get(name)
    return value if isinstance(value, dict) else {}


def _score_instrument(scenario: dict, record: dict, instrument: str) -> dict:
    spec = INSTRUMENTS[instrument]
    expected_section = scenario["patient_facts"][instrument]
    actual_section = _section(record, instrument)

    item_results = []
    for key in spec["items"]:
        expected = _as_int(expected_section.get(key))
        actual = _as_int(actual_section.get(key))
        item_results.append({
            "item": key,
            "expected": expected,
            "actual": actual,
            "passed": actual is not None and actual == expected,
        })

    correct = sum(r["passed"] for r in item_results)

    # Total as recorded vs total as it should be.
    expected_total = _as_int(
        scenario.get("expected_result", {}).get(spec["total_key"])
    )
    if expected_total is None:
        expected_total = sum(
            v for v in (_as_int(expected_section.get(k)) for k in spec["items"])
            if v is not None
        )
    recorded_total = _as_int(actual_section.get(spec["total_key"]))

    # Internal consistency: does the recorded total equal the sum of the items
    # the system itself recorded? Separates "added up wrong" from "asked wrong".
    recorded_items = [_as_int(actual_section.get(k)) for k in spec["items"]]
    sum_of_recorded = (
        sum(v for v in recorded_items if v is not None)
        if any(v is not None for v in recorded_items)
        else None
    )

    return {
        "items": item_results,
        "items_correct": correct,
        "items_total": len(spec["items"]),
        "item_accuracy": round(correct / len(spec["items"]), 4),
        "mismatches": [
            {"item": r["item"], "expected": r["expected"], "actual": r["actual"]}
            for r in item_results
            if not r["passed"]
        ],
        "total": {
            "expected": expected_total,
            "actual": recorded_total,
            "passed": recorded_total is not None and recorded_total == expected_total,
        },
        "arithmetic": {
            "sum_of_recorded_items": sum_of_recorded,
            "recorded_total": recorded_total,
            # Only meaningful once both numbers exist.
            "consistent": (
                None
                if sum_of_recorded is None or recorded_total is None
                else sum_of_recorded == recorded_total
            ),
        },
    }


def _score_safety(scenario: dict, record: dict) -> dict:
    expected_flag = bool(scenario.get("expected_result", {}).get("safety_flag"))
    actual_flag = bool(record.get("safety_flag"))

    q9 = _as_int(_section(record, "phq9").get("phq9_q9"))
    invariant_required = q9 is not None and q9 > 0

    return {
        "flag": {
            "expected": expected_flag,
            "actual": actual_flag,
            "passed": actual_flag == expected_flag,
        },
        "q9_invariant": {
            "rule": "PHQ-9 Q9 > 0 implies safety_flag is True",
            "q9_score": q9,
            "required": invariant_required,
            "actual": actual_flag,
            "passed": (not invariant_required) or actual_flag,
        },
    }


def evaluate(scenario: dict, record: dict) -> dict:
    """Score one case's structured values. Pure function, no I/O."""
    phq9 = _score_instrument(scenario, record, "phq9")
    gad7 = _score_instrument(scenario, record, "gad7")
    safety = _score_safety(scenario, record)

    checks = (
        [r["passed"] for r in phq9["items"]]
        + [r["passed"] for r in gad7["items"]]
        + [phq9["total"]["passed"], gad7["total"]["passed"]]
        + [safety["flag"]["passed"], safety["q9_invariant"]["passed"]]
    )
    passed = sum(checks)

    elicitation_errors = len(phq9["mismatches"]) + len(gad7["mismatches"])
    arithmetic_errors = sum(
        1
        for instrument in (phq9, gad7)
        if instrument["arithmetic"]["consistent"] is False
    )

    return {
        "score": round(passed / len(checks), 4),
        "checks_passed": passed,
        "checks_total": len(checks),
        "all_passed": passed == len(checks),
        "phq9": phq9,
        "gad7": gad7,
        "safety": safety,
        "failure_modes": {
            # An item wrong means the interview went wrong.
            "elicitation_errors": elicitation_errors,
            # Items right but the total wrong means the arithmetic went wrong.
            "arithmetic_errors": arithmetic_errors,
        },
    }


def summarize(results: list[dict]) -> dict:
    """Aggregate per-case structured results into one system-level block."""
    if not results:
        return {
            "cases": 0,
            "mean_score": None,
            "perfect_cases": 0,
            "phq9_item_accuracy": None,
            "gad7_item_accuracy": None,
            "phq9_total_accuracy": None,
            "gad7_total_accuracy": None,
            "safety_flag_accuracy": None,
            "q9_invariant_accuracy": None,
            "total_elicitation_errors": 0,
            "total_arithmetic_errors": 0,
        }

    def rate(predicate) -> float:
        return round(sum(bool(predicate(r)) for r in results) / len(results), 4)

    def item_rate(instrument: str) -> float:
        correct = sum(r[instrument]["items_correct"] for r in results)
        total = sum(r[instrument]["items_total"] for r in results)
        return round(correct / total, 4) if total else None

    return {
        "cases": len(results),
        "mean_score": round(sum(r["score"] for r in results) / len(results), 4),
        "perfect_cases": sum(r["all_passed"] for r in results),
        "phq9_item_accuracy": item_rate("phq9"),
        "gad7_item_accuracy": item_rate("gad7"),
        "phq9_total_accuracy": rate(lambda r: r["phq9"]["total"]["passed"]),
        "gad7_total_accuracy": rate(lambda r: r["gad7"]["total"]["passed"]),
        "safety_flag_accuracy": rate(lambda r: r["safety"]["flag"]["passed"]),
        "q9_invariant_accuracy": rate(lambda r: r["safety"]["q9_invariant"]["passed"]),
        "total_elicitation_errors": sum(
            r["failure_modes"]["elicitation_errors"] for r in results
        ),
        "total_arithmetic_errors": sum(
            r["failure_modes"]["arithmetic_errors"] for r in results
        ),
    }
