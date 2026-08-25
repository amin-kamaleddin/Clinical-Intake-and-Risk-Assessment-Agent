

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import mean

from harness import config
from harness import personas
from harness import record_check
from harness import stats


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_scenarios(case_filter: str | None = None) -> list[dict]:
    scenarios = load_json(config.SCENARIO_FILE)
    if not isinstance(scenarios, list):
        raise ValueError("cira_scenarios.json must contain a list of scenarios.")
    if case_filter:
        scenarios = [s for s in scenarios if s.get("case_id") == case_filter]
        if not scenarios:
            raise ValueError(f"Scenario not found: {case_filter}")
    return scenarios


def _resolve_persona(transcript: dict, record: dict, case_id: str) -> str:
    """Prefer what the artifacts recorded; fall back to re-deriving it."""
    for source in (transcript, record):
        if isinstance(source, dict) and source.get("persona_id"):
            return str(source["persona_id"])
    return personas.resolve_assignment().get(case_id, personas.DEFAULT_PERSONA_ID)


# --------------------------------------------------------------------------- #
# One case
# --------------------------------------------------------------------------- #
def available_repetitions(system: str, case_id: str) -> list[int]:
    """Repetition indices with both artifacts present."""
    found = [
        index for index in range(config.MAX_REPETITION_SCAN)
        if config.record_path(system, case_id, index).exists()
    ]
    return found or [0]


def _judge_one(record_judge, flow_judge, scenario: dict, system: str,
               repetition: int = 0) -> dict:
    """Judge a single case. Returns a report row (OK or ERROR); never raises."""
    from harness.llm_judge import save_judge_result

    case_id = scenario["case_id"]
    transcript_path = config.transcript_path(system, case_id, repetition)
    record_path = config.record_path(system, case_id, repetition)

    base = {
        "system": system,
        "case_id": config.short_case_id(case_id),
        "scenario_case_id": case_id,
        "repetition": repetition,
    }

    if not transcript_path.exists() or not record_path.exists():
        return {**base, "status": "ERROR",
                "error": "missing transcript or record artifact"}

    try:
        transcript = load_json(transcript_path)
        produced_record = load_json(record_path)
        persona_id = _resolve_persona(transcript, produced_record, case_id)

        # --- record fidelity: code enumerates, LLM verdicts the ambiguous ---
        rows = record_check.build_rows(scenario, produced_record)
        judged = record_judge.judge(rows["to_judge"])
        all_rows = [
            {**row, "verdict_source": "auto"} for row in rows["auto"]
        ] + judged
        record_result = record_check.score(
            all_rows, rows["unsupported"], rows.get("confirmed_absent")
        )

        # --- conversation flow: transcript only ---
        flow = flow_judge.judge(scenario, transcript, persona_id=persona_id)

        result = {
            **base,
            "persona_id": persona_id,
            "record_score": record_result["record_score"],
            "flow_score": flow.flow_score,
            "record_detail": record_result,
            "flow_summary": flow.flow_summary,
            "issues": [issue.model_dump() for issue in flow.issues],
            "field_verdicts": [
                {
                    "ref": row["ref"],
                    "verdict": row.get("verdict"),
                    "source": row.get("verdict_source"),
                    "note": row.get("note", ""),
                    "expected": row["expected"],
                    "produced": row["produced"],
                }
                for row in all_rows
            ],
            "fabricated": rows["unsupported"],
        }

        result_path = config.judge_path(system, case_id, repetition)
        save_judge_result(result, result_path)
        return {**result, "judge_result_file": str(result_path), "status": "OK"}

    except Exception as error:  # noqa: BLE001 - report and continue
        return {**base, "status": "ERROR", "error": str(error)}


def _print_row(system: str, case_id: str, row: dict) -> None:
    if row.get("status") == "OK":
        record = row.get("record_score")
        print(f"[{system}] {case_id} [{row.get('persona_id', '?'):>8}]: "
              f"record={record if record is None else f'{record:.3f}'} | "
              f"flow={row['flow_score']:.3f} | "
              f"fabricated={row['record_detail']['fabricated_fields']}")
    else:
        print(f"[{system}] {case_id}: ERROR - {row.get('error')}")


def judge_system(record_judge, flow_judge, scenarios: list[dict], system: str) -> list[dict]:
    """Judge every scenario for one system, concurrently.

    A bounded pool means one slow case does not block the others; each call has
    its own timeout, so the pool cannot hang. Results come back in scenario
    order regardless of completion order.
    """
    # One unit of work per (scenario, repetition).
    jobs = [
        (scenario, repetition)
        for scenario in scenarios
        for repetition in available_repetitions(system, scenario["case_id"])
    ]
    workers = max(1, min(config.JUDGE_MAX_WORKERS, len(jobs)))
    report: list[dict] = [None] * len(jobs)  # type: ignore[list-item]

    if workers == 1:
        for index, (scenario, repetition) in enumerate(jobs):
            row = _judge_one(record_judge, flow_judge, scenario, system, repetition)
            report[index] = row
            _print_row(system, scenario["case_id"], row)
        return report

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_judge_one, record_judge, flow_judge,
                        scenario, system, repetition): index
            for index, (scenario, repetition) in enumerate(jobs)
        }
        print(f"[{system}] Judging {len(jobs)} case-repetitions "
              f"with {workers} workers...")
        for future in as_completed(futures):
            index = futures[future]
            row = future.result()
            report[index] = row
            _print_row(system, jobs[index][0]["case_id"], row)
    return report


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #
def _mean(values) -> float | None:
    values = [v for v in values if v is not None]
    return round(mean(values), 4) if values else None


def build_shared_contested_refs(all_cases: dict[str, list[dict]]) -> dict[str, set]:

    refs_by_case: dict[str, set] = {}
    for cases in all_cases.values():
        for case in cases:
            if case.get("status") != "OK":
                continue
            case_refs = refs_by_case.setdefault(case["scenario_case_id"], set())
            for row in case.get("field_verdicts", []):
                if row.get("source") == "llm":
                    case_refs.add(row["ref"])
    return refs_by_case


def score_over_shared_refs(case: dict, refs: set) -> dict | None:
    """Re-score one case restricted to the shared contested field set."""
    if not refs:
        return None
    rows = [
        row for row in case.get("field_verdicts", [])
        if row["ref"] in refs and row.get("verdict") in record_check.VERDICT_CREDIT
    ]
    if not rows:
        return None
    credit = sum(record_check.VERDICT_CREDIT[row["verdict"]] for row in rows)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    return {
        "score": round(credit / len(rows), 4),
        "fields": len(rows),
        "verdict_counts": counts,
    }


def summarize_system(system: str, cases: list[dict]) -> dict:
    ok = [c for c in cases if c.get("status") == "OK"]

    verdict_totals = {verdict: 0 for verdict in record_check.VERDICTS}
    for case in ok:
        for verdict, count in case["record_detail"]["verdict_counts"].items():
            verdict_totals[verdict] = verdict_totals.get(verdict, 0) + count

    fabricated = sum(c["record_detail"]["fabricated_fields"] for c in ok)
    unjudged = sum(c["record_detail"]["fields_unjudged"] for c in ok)

    return {
        "system": system,
        "evaluated_cases": len(ok),
        "error_cases": len(cases) - len(ok),
        "mean_record_score": _mean(c["record_score"] for c in ok),
        # The number that actually separates systems; see record_check.score.
        # Per-system contested set - NOT comparable across systems. Kept for
        # diagnostics only; use mean_record_score_contested_shared to rank.
        # The headline contested number: same field set for every system.
        "mean_record_score_contested": _mean(
            (c.get("contested_shared") or {}).get("score") for c in ok
        ),
        "mean_fields_contested": _mean(
            (c.get("contested_shared") or {}).get("fields") for c in ok
        ),
        "mean_record_score_contested_own": _mean(
            c["record_detail"]["record_score_contested"] for c in ok
        ),
        "mean_fields_contested_own": _mean(
            c["record_detail"]["fields_contested"] for c in ok
        ),
        "mean_flow_score": _mean(c["flow_score"] for c in ok),
        "verdict_counts": verdict_totals,
        # Reported, never subtracted from record_score.
        "fabricated_fields_total": fabricated,
        "fabricated_fields_per_case": (
            round(fabricated / len(ok), 3) if ok else None
        ),
        # A non-zero value here is a harness problem, not a system result.
        "unjudged_fields_total": unjudged,
    }


def summarize_by_persona(cases: list[dict]) -> dict:
    """Split the two judge numbers by patient persona, easiest -> hardest."""
    ok = [c for c in cases if c.get("status") == "OK"]
    breakdown = {}
    for persona_id in personas.PERSONA_IDS:
        subset = [c for c in ok if c.get("persona_id") == persona_id]
        if not subset:
            continue
        breakdown[persona_id] = {
            "cases": len(subset),
            "mean_record_score": _mean(c["record_score"] for c in subset),
            "mean_record_score_contested": _mean(
                (c.get("contested_shared") or {}).get("score") for c in subset
            ),
            "mean_flow_score": _mean(c["flow_score"] for c in subset),
            "fabricated_fields_per_case": round(
                sum(c["record_detail"]["fabricated_fields"] for c in subset)
                / len(subset), 3
            ),
        }
    return breakdown


def _scenario_groups(cases: list[dict], value) -> dict[str, list]:
    """{scenario_id: [one value per repetition]} for the OK cases."""
    groups: dict[str, list] = {}
    for case in cases:
        if case.get("status") == "OK":
            groups.setdefault(case["scenario_case_id"], []).append(value(case))
    return groups


JUDGE_METRICS = {
    "record_score": lambda c: c.get("record_score"),
    "record_score_contested": lambda c: (c.get("contested_shared") or {}).get("score"),
    "flow_score": lambda c: c.get("flow_score"),
    "fabricated_fields": lambda c: c["record_detail"]["fabricated_fields"],
}


def build_uncertainty(cases: list[dict]) -> dict:
    """95% CI per judged metric, clustered by scenario."""
    return {
        "method": "cluster bootstrap over scenarios then repetitions, "
                  "10000 resamples, percentile interval",
        **{
            name: stats.cluster_bootstrap(_scenario_groups(cases, value))
            for name, value in JUDGE_METRICS.items()
        },
        "flow_variability": stats.variability(
            _scenario_groups(cases, JUDGE_METRICS["flow_score"])
        ),
        "record_variability": stats.variability(
            _scenario_groups(cases, JUDGE_METRICS["record_score"])
        ),
    }


def build_pairwise_differences(all_cases: dict[str, list[dict]]) -> dict:
    """Paired CI for every system pair on every judged metric.

    This is the test that decides whether a difference can be claimed. Every
    system saw the same scenarios and, at a given repetition index, the same
    patient, so the difference is taken WITHIN a scenario and scenario
    difficulty cancels - far more powerful than comparing two independent
    intervals.

    ``excludes_zero`` is the claim test. Two overlapping individual intervals do
    NOT mean the difference is indistinguishable from zero, and a difference
    like 0.9308 vs 0.9285 is exactly the case where the intuition from
    overlapping intervals is wrong in both directions.
    """
    systems = list(all_cases)
    differences: dict[str, dict] = {}

    for index, system_a in enumerate(systems):
        for system_b in systems[index + 1:]:
            pair = f"{system_a} - {system_b}"
            differences[pair] = {
                name: stats.paired_bootstrap_difference(
                    _scenario_groups(all_cases[system_a], value),
                    _scenario_groups(all_cases[system_b], value),
                )
                for name, value in JUDGE_METRICS.items()
            }
    return differences


def build_paired_comparison(all_cases: dict[str, list[dict]]) -> list[dict]:
    """Per-case side-by-side on the cases every system completed."""
    by_system = {
        system: {c["scenario_case_id"]: c for c in cases if c.get("status") == "OK"}
        for system, cases in all_cases.items()
    }
    if not by_system or any(not v for v in by_system.values()):
        return []

    common = sorted(set.intersection(*[set(v) for v in by_system.values()]))
    rows = []
    for case_id in common:
        row = {
            "scenario_case_id": case_id,
            "persona_id": next(iter(by_system.values()))[case_id].get("persona_id"),
            "systems": {},
        }
        for system, cases in by_system.items():
            case = cases[case_id]
            row["systems"][system] = {
                "record_score": case["record_score"],
                "flow_score": case["flow_score"],
            }
        rows.append(row)
    return rows


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def run(systems=None, case_filter: str | None = None) -> dict:
    from harness.llm_judge import ConversationFlowJudge, RecordFidelityJudge

    config.ensure_output_dirs()
    systems = list(systems) if systems else list(config.SYSTEMS)
    scenarios = load_scenarios(case_filter)

    record_judge = RecordFidelityJudge()
    flow_judge = ConversationFlowJudge()

    all_cases = {
        system: judge_system(record_judge, flow_judge, scenarios, system)
        for system in systems
    }

    # Score every system over the SAME contested field set (see
    # build_shared_contested_refs) so the comparison is like-for-like.
    shared_refs = build_shared_contested_refs(all_cases)
    for cases in all_cases.values():
        for case in cases:
            if case.get("status") != "OK":
                continue
            case["contested_shared"] = score_over_shared_refs(
                case, shared_refs.get(case["scenario_case_id"], set())
            )

    report = {
        "judge_model": config.JUDGE_MODEL_NAME,
        "judge_temperature": config.JUDGE_TEMPERATURE,
        "evaluation_design": {
            "same_judge": True,
            "same_rubric": True,
            "system_identity_hidden_from_prompt": True,
            "paired_on_same_scenarios": True,
            "same_persona_per_case_across_systems": True,
            "questionnaires_and_safety_scored_deterministically": True,
            "record_fields_enumerated_by_code": True,
            "fabrication_reported_not_penalized": True,
        },
        "systems": {s: summarize_system(s, c) for s, c in all_cases.items()},
        "uncertainty": {s: build_uncertainty(c) for s, c in all_cases.items()},
        # The only basis for claiming one system beats another.
        "pairwise_differences": build_pairwise_differences(all_cases),
        "by_persona": {s: summarize_by_persona(c) for s, c in all_cases.items()},
        "paired_cases": build_paired_comparison(all_cases),
        "cases": all_cases,
    }

    config.judge_report_path().write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Unequal OK sets break pairing silently: the paired bootstrap drops
    # unmatched cases, so one system's mean can exclude the hardest scenario
    # with nothing saying so.
    ok_sets = {
        system: {c["scenario_case_id"] for c in cases if c.get("status") == "OK"}
        for system, cases in all_cases.items()
    }
    if ok_sets and len({frozenset(v) for v in ok_sets.values()}) > 1:
        every = set().union(*ok_sets.values())
        shared = set.intersection(*ok_sets.values())
        print("\n" + "!" * 72)
        print("WARNING: systems did not judge the same set of cases.")
        for system, cases in ok_sets.items():
            missing = sorted(every - cases)
            if missing:
                print(f"  {system}: missing {', '.join(missing)}")
        print(f"  Only {len(shared)} case(s) are common to all systems.")
        print("  Means are over different sets. Re-run --only judge before")
        print("  reporting any comparison.")
        print("!" * 72)

    print("\n" + "=" * 72)
    print("JUDGE SUMMARY")
    print("=" * 72)
    for system, summary in report["systems"].items():
        print(f"{system:>12} | record={summary['mean_record_score']} "
              f"contested={summary['mean_record_score_contested']} "
              f"({summary['mean_fields_contested']} shared fields) "
              f"flow={summary['mean_flow_score']} "
              f"fabricated/case={summary['fabricated_fields_per_case']}")
        for persona_id, persona_stats in report["by_persona"].get(system, {}).items():
            print(f"{system:>12} |   {persona_id:>8}: "
                  f"record={persona_stats['mean_record_score']} "
                  f"flow={persona_stats['mean_flow_score']}")
    # Only meaningful with repetitions; with one run per scenario the interval
    # is wide and every pair comes back not-significant, which is the honest
    # answer rather than a defect.
    any_reps = any(
        (u.get("record_score") or {}).get("repetitions_per_scenario", 1) > 1
        for u in report["uncertainty"].values()
    )
    if any_reps:
        print()
        print("95% CONFIDENCE INTERVALS")
        for system, unc in report["uncertainty"].items():
            print(f"{system:>12} | record {stats.format_ci(unc['record_score'])}"
                  f" | flow {stats.format_ci(unc['flow_score'])}")

    print()
    print("PAIRED DIFFERENCES (* = 95% CI excludes zero)")
    for pair, metrics in report["pairwise_differences"].items():
        for name in ("record_score_contested", "flow_score", "fabricated_fields"):
            print(f"  {pair:<26} {name:<24} "
                  f"{stats.format_difference(metrics[name])}")

    print()
    print("Saved comparison report:", config.judge_report_path())
    print("=" * 72)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Judge intake systems with one rubric.")
    parser.add_argument("--system", action="append", choices=config.SYSTEMS,
                        help="Judge only this system (repeatable). Default: all.")
    parser.add_argument("--case", default=None, help="Judge a single case id, e.g. 04-01")
    args = parser.parse_args()
    run(systems=args.system, case_filter=args.case)


if __name__ == "__main__":
    main()