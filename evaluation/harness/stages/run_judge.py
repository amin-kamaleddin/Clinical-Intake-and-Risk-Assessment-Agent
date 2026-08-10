"""Stage 4 - LLM judging: record fidelity and conversation flow.

Two calls per case, each producing one number:

* ``record_score``  - fields enumerated by ``harness.record_check``, verdicted
  categorically by the LLM, aggregated back into a number by code. Exact and
  boolean matches are auto-resolved without the model.
* ``flow_score``    - one holistic 0-1 score for interviewing quality from the
  transcript alone.

Separate calls, not one combined call: shorter prompts judge more reliably, and
a record failure cannot bleed into the flow number or vice versa. At 12 cases
across 3 systems that is 72 calls, so the extra cost is negligible.

PHQ-9, GAD-7 and the safety flag are NOT judged here. They have exact expected
values and belong to ``harness.structured_score``, which the deterministic
scoring stage runs. Nothing is scored twice.

Reads:   outputs/<system>/transcripts/case_XX.json
         outputs/<system>/records/case_XX.json
Writes:  outputs/judge/<system>/case_XX.json
         outputs/reports/judge_comparison.json

Run directly::

    python -m harness.stages.run_judge
    python -m harness.stages.run_judge --case 04-01 --system cira
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import mean

from harness import config
from harness import personas
from harness import record_check


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
def _judge_one(record_judge, flow_judge, scenario: dict, system: str) -> dict:
    """Judge a single case. Returns a report row (OK or ERROR); never raises."""
    from harness.llm_judge import save_judge_result

    case_id = scenario["case_id"]
    transcript_path = config.transcript_path(system, case_id)
    record_path = config.record_path(system, case_id)

    base = {
        "system": system,
        "case_id": config.short_case_id(case_id),
        "scenario_case_id": case_id,
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

        result_path = config.judge_path(system, case_id)
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
    workers = max(1, min(config.JUDGE_MAX_WORKERS, len(scenarios)))
    report: list[dict] = [None] * len(scenarios)  # type: ignore[list-item]

    if workers == 1:
        for index, scenario in enumerate(scenarios):
            row = _judge_one(record_judge, flow_judge, scenario, system)
            report[index] = row
            _print_row(system, scenario["case_id"], row)
        return report

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_judge_one, record_judge, flow_judge, scenario, system): index
            for index, scenario in enumerate(scenarios)
        }
        print(f"[{system}] Judging {len(scenarios)} cases with {workers} workers...")
        for future in as_completed(futures):
            index = futures[future]
            row = future.result()
            report[index] = row
            _print_row(system, scenarios[index]["case_id"], row)
    return report


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #
def _mean(values) -> float | None:
    values = [v for v in values if v is not None]
    return round(mean(values), 4) if values else None


def build_shared_contested_refs(all_cases: dict[str, list[dict]]) -> dict[str, set]:
    """Per case, the UNION of field refs any system needed the judge for.

    ``record_detail.record_score_contested`` is computed per system, over that
    system's own judged rows. That makes it uncomparable: a row is auto-resolved
    in code when the produced value matches ground truth exactly, so a system
    that writes verbatim-correct values removes its own easy wins from its own
    denominator and is left being scored on the hard residue.

    On this run that skew was severe - 12.1 contested fields per case for one
    system against 21.8 for another, from an identical 44-field pool. The
    resulting "contested" ranking was an artifact of which fields each system
    happened to ace, not of capture quality.

    Scoring every system over the union fixes it: if ANY system needed a
    judgement on a field, ALL systems are scored on that field, using whatever
    verdict they got (including auto-resolved ones). Same exam for everyone.
    """
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
        "by_persona": {s: summarize_by_persona(c) for s, c in all_cases.items()},
        "paired_cases": build_paired_comparison(all_cases),
        "cases": all_cases,
    }

    config.JUDGE_REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n" + "=" * 72)
    print("JUDGE SUMMARY")
    print("=" * 72)
    for system, summary in report["systems"].items():
        print(f"{system:>12} | record={summary['mean_record_score']} "
              f"contested={summary['mean_record_score_contested']} "
              f"({summary['mean_fields_contested']} shared fields) "
              f"flow={summary['mean_flow_score']} "
              f"fabricated/case={summary['fabricated_fields_per_case']}")
        for persona_id, stats in report["by_persona"].get(system, {}).items():
            print(f"{system:>12} |   {persona_id:>8}: "
                  f"record={stats['mean_record_score']} "
                  f"flow={stats['mean_flow_score']}")
    print("Saved comparison report:", config.JUDGE_REPORT_PATH)
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
