

from __future__ import annotations

import argparse
import atexit
import json
import time

from harness import config
from harness import personas
from harness import provenance
from harness.stages import run_cira, run_rule_based, run_naive, run_judge, score_records


STAGES = ["cira", "rule_based", "naive_llm", "score", "judge", "summary"]


def _has_artifacts(system: str) -> bool:
    return any(config.record_dir(system).glob("case_*.json"))


def stage_cira(case_filter, persona_options):
    try:
        run_cira.run(case_filter=case_filter, **persona_options)
    except Exception as error:  # noqa: BLE001
        print(f"\n[cira] SKIPPED: {error}\n")


def stage_rule_based(case_filter, persona_options):
    try:
        run_rule_based.run(case_filter=case_filter, **persona_options)
    except Exception as error:  # noqa: BLE001
        print(f"\n[rule_based] SKIPPED: {error}\n")


def stage_naive(case_filter, persona_options):
    try:
        run_naive.run(case_filter=case_filter, **persona_options)
    except Exception as error:  # noqa: BLE001
        print(f"\n[naive_llm] SKIPPED: {error}\n")


def stage_score(systems, case_filter):
    for system in systems:
        if not _has_artifacts(system):
            print(f"[score] no {system} artifacts; skipping")
            continue
        try:
            score_records.run(system, case_filter=case_filter)
        except Exception as error:  # noqa: BLE001
            print(f"[score:{system}] SKIPPED: {error}")


def stage_judge(systems, case_filter):
    judgeable = [s for s in systems if _has_artifacts(s)]
    if not judgeable:
        print("[judge] no artifacts for any system; skipping")
        return
    try:
        run_judge.run(systems=judgeable, case_filter=case_filter)
    except Exception as error:  # noqa: BLE001
        print(f"[judge] SKIPPED: {error}")


def stage_summary(systems, repetitions=None):
    """Combine the deterministic and judge reports into one file."""
    summary = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "systems": {}}

    # Provenance: which models, prompts, scenarios and code produced this.
    summary["provenance"] = provenance.load_manifest()
    # Read the count this run actually used. Reading config.REPETITIONS here
    # meant `--repetitions 3` produced three realisations per scenario and then
    # filed them as one, which silently understates the evidence behind every
    # interval in the report.
    summary["repetitions"] = (
        repetitions if repetitions is not None else config.REPETITIONS
    )
    freshness = provenance.check_artifact_freshness(systems)
    summary["artifact_freshness"] = freshness
    if not freshness["clean"]:
        print(provenance.format_freshness(freshness))

    # Record which patients produced these numbers. Without it a summary is not
    # reproducible: the seed is what makes two runs comparable.
    if config.PERSONA_ASSIGNMENT_PATH.exists():
        assignment = json.loads(
            config.PERSONA_ASSIGNMENT_PATH.read_text(encoding="utf-8")
        )
        summary["personas"] = {
            "seed": assignment.get("seed"),
            "strategy": assignment.get("strategy"),
            "override": assignment.get("override"),
            "counts": assignment.get("counts"),
            "assignment": assignment.get("assignment"),
        }

    for system in systems:
        entry = {}
        det_path = config.deterministic_report_path(system)
        if det_path.exists():
            det = json.loads(det_path.read_text(encoding="utf-8"))
            entry["deterministic"] = det.get("summary")
            entry["by_persona"] = (det.get("summary") or {}).get("by_persona")
            entry["structured"] = (det.get("summary") or {}).get("structured")
            entry["safety"] = (det.get("summary") or {}).get("safety")
            entry["budget"] = (det.get("summary") or {}).get("budget")
        summary["systems"][system] = entry

    if config.JUDGE_REPORT_PATH.exists():
        judge = json.loads(config.JUDGE_REPORT_PATH.read_text(encoding="utf-8"))
        summary["judge"] = {
            "judge_model": judge.get("judge_model"),
            "evaluation_design": judge.get("evaluation_design"),
            "systems": judge.get("systems"),
            "by_persona": judge.get("by_persona"),
            "paired_cases": judge.get("paired_cases"),
        }
        # Uncertainty travels with the summary, so a reader of summary.json
        # alone can tell which differences are claimable.
        summary["uncertainty"] = judge.get("uncertainty")
        summary["pairwise_differences"] = judge.get("pairwise_differences")
        for system, judge_summary in judge.get("systems", {}).items():
            summary["systems"].setdefault(system, {})["judge"] = judge_summary

    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    # Computed before the write so it persists in summary.json; the printed
    # table below reads the same values.
    budgets = {
        system: entry["budget"]
        for system, entry in summary["systems"].items() if entry.get("budget")
    }
    if budgets:
        from harness import budget as budget_module
        summary["budget_comparison"] = budget_module.compare(budgets)

    config.SUMMARY_REPORT_PATH.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("\n" + "=" * 72)
    print("COMBINED SUMMARY")
    print("=" * 72)
    # Four metrics, each with a defensible definition. Everything else in the
    # reports is a diagnostic and is deliberately not printed here: a reviewer
    # reading this table should see only numbers that can be defended.
    print("PRIMARY METRICS")
    print(f"{'system':>12} | {'safety':>7} {'structured':>10} "
          f"{'record*':>8} {'flow':>7} {'fabricated/case':>16}")
    print("-" * 74)
    for system, entry in summary["systems"].items():
        struct = (entry.get("structured") or {}).get("mean_score")
        jdg = entry.get("judge") or {}
        safety = entry.get("safety") or {}
        print(f"{system:>12} | {str(safety.get('safety_score')):>7} "
              f"{str(struct):>10} "
              f"{str(jdg.get('mean_record_score_contested')):>8} "
              f"{str(jdg.get('mean_flow_score')):>7} "
              f"{str(jdg.get('fabricated_fields_per_case')):>16}")
        if safety.get("missed_risk_cases"):
            print(f"{system:>12} |   *** MISSED RISK on "
                  f"{', '.join(safety['missed_risk_cases'])} ***")
        if safety.get("false_alarm_cases"):
            print(f"{system:>12} |   false alarm on "
                  f"{', '.join(safety['false_alarm_cases'])} "
                  f"(distractor specificity "
                  f"{safety.get('distractor_specificity')})")
    # Degradation across patient difficulty - the result the personas exist for.
    print()
    print("BY PATIENT DIFFICULTY (easiest -> hardest)")
    print(f"{'system':>12} | {'persona':>9} | {'structured':>10} {'record':>8} {'flow':>7}")
    print("-" * 62)
    for system, entry in summary["systems"].items():
        for persona_id, persona_stats in (entry.get("by_persona") or {}).items():
            judge_persona = (
                (summary.get("judge", {}).get("by_persona", {}) or {})
                .get(system, {})
                .get(persona_id, {})
            )
            print(f"{system:>12} | {persona_id:>9} | "
                  f"{str(persona_stats['mean_structured_score']):>10} "
                  f"{str(judge_persona.get('mean_record_score')):>8} "
                  f"{str(judge_persona.get('mean_flow_score')):>7}")

    print()
    print("* record = shared contested field set (same fields scored for every")
    print("  system). Overall record score and per-system contested sets are in")
    print("  summary.json; process checks are diagnostics and are not scored.")
    print("Summary saved to:", config.SUMMARY_REPORT_PATH)
    print("=" * 72)


    if budgets:
        print()
        print(budget_module.format_summary(
            budgets, summary.get("budget_comparison") or {}
        ))

    try:
        from tools.show_intervals import print_intervals
        print()
        print_intervals()
    except Exception as error:  # noqa: BLE001 - never let formatting kill a run
        print(f"(intervals unavailable: {error})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the full CIRA evaluation.")
    parser.add_argument("--only", nargs="+", choices=STAGES,
                        help="Run only these stages.")
    parser.add_argument("--skip", nargs="+", choices=STAGES,
                        help="Skip these stages.")
    parser.add_argument("--systems", nargs="+", choices=config.SYSTEMS,
                        help="Limit scoring/judging to these systems. Default: both.")
    parser.add_argument("--case", default=None, help="Restrict to one case id, e.g. 04-01")
    parser.add_argument("--force-lock", action="store_true",
                        help="Start even if another run holds outputs/. Only "
                             "when you are certain that process is not writing.")
    parser.add_argument("--repetitions", type=int, default=None,
                        help="Independent interactions per scenario. More "
                             "repetitions narrow the confidence intervals; "
                             "cost scales linearly. Default 1 (no intervals).")
    parser.add_argument("--persona-seed", type=int, default=None,
                        help=f"Seed for persona assignment (default {config.PERSONA_SEED}).")
    parser.add_argument("--persona-strategy", choices=personas.ASSIGNMENT_STRATEGIES,
                        default=None,
                        help="balanced (equal counts, default) or random (i.i.d.).")
    parser.add_argument("--persona", choices=personas.PERSONA_IDS, default=None,
                        help="Force every case onto one persona (stress ablation).")
    args = parser.parse_args()

    stages = list(args.only) if args.only else list(STAGES)
    if args.skip:
        stages = [s for s in stages if s not in args.skip]
    systems = list(args.systems) if args.systems else list(config.SYSTEMS)

    config.ensure_output_dirs()

    persona_options = {
        "persona_override": args.persona or config.PERSONA_OVERRIDE,
        "persona_seed": args.persona_seed,
        "persona_strategy": args.persona_strategy,
        "repetitions": args.repetitions,
    }


    manifest = provenance.write_manifest(repetitions=args.repetitions)

    # Claim outputs/ before any stage writes to it. Refuses if another run is
    # live; reclaims automatically if the previous holder is gone.
    try:
        provenance.acquire_lock(manifest["run_id"], force=args.force_lock)
    except RuntimeError as error:
        print(f"\nREFUSING TO START: {error}\n")
        raise SystemExit(1)
    atexit.register(provenance.release_lock)

    persona_report = personas.write_assignment(
        seed=args.persona_seed,
        strategy=args.persona_strategy,
        override=persona_options["persona_override"],
    )

    print("=" * 72)
    print("CIRA FULL EVALUATION")
    print("Stages:", ", ".join(stages))
    print("Systems:", ", ".join(systems))
    if args.case:
        print("Case filter:", args.case)
    repetitions = args.repetitions or config.REPETITIONS
    print(f"Run id: {manifest['run_id']}   code: {manifest['code_revision']}")
    print(f"Repetitions per scenario: {repetitions}"
          + ("   (single run - no confidence intervals)" if repetitions < 2 else ""))
    print(f"Models: cira={manifest['models']['cira']} "
          f"patient={manifest['models']['patient_simulator']} "
          f"judge={manifest['models']['judge']}")
    print("=" * 72)
    print(personas.format_assignment_table(persona_report))

    if "cira" in stages and "cira" in systems:
        stage_cira(args.case, persona_options)
    if "rule_based" in stages and "rule_based" in systems:
        stage_rule_based(args.case, persona_options)
    if "naive_llm" in stages and "naive_llm" in systems:
        stage_naive(args.case, persona_options)
    if "score" in stages:
        stage_score(systems, args.case)
    if "judge" in stages:
        stage_judge(systems, args.case)
    if "summary" in stages:
        stage_summary(systems, repetitions=repetitions)


if __name__ == "__main__":
    main()
