"""Run the whole CIRA evaluation with one command.

Pipeline
--------
1. cira        - drive the live CIRA agent          -> outputs/cira/{transcripts,records}
2. rule_based  - run the rule-based baseline        -> outputs/rule_based/{transcripts,records}
3. score       - deterministic checks for BOTH      -> outputs/reports/<system>_deterministic.json
4. judge       - blinded LLM judge for BOTH         -> outputs/judge/... + reports/judge_comparison.json
5. summary     - combine everything                 -> outputs/reports/summary.json

Usage
-----
    python run_all.py                      # everything
    python run_all.py --case 04-01         # one scenario end-to-end
    python run_all.py --skip cira          # e.g. no live agent available
    python run_all.py --only rule_based score
    python run_all.py --systems rule_based # limit scoring/judging to one system

Notes
-----
* Stages that need external services (the live CIRA package, LLM API keys for the
  patient simulator and judge) fail gracefully: the failure is reported and the
  run continues, so a partial environment still produces whatever it can.
* Deterministic scoring and judging only run for systems whose artifacts exist.
"""

from __future__ import annotations

import argparse
import json
import time

from harness import config
from harness import personas
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


def stage_summary(systems):
    """Combine the deterministic and judge reports into one file."""
    summary = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "systems": {}}

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
        for system, judge_summary in judge.get("systems", {}).items():
            summary["systems"].setdefault(system, {})["judge"] = judge_summary

    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    config.SUMMARY_REPORT_PATH.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("\n" + "=" * 72)
    print("COMBINED SUMMARY")
    print("=" * 72)
    print(f"{'system':>12} | {'structured':>10} {'record':>8} {'flow':>8} "
          f"{'fabricated/case':>16}")
    print("-" * 72)
    for system, entry in summary["systems"].items():
        struct = (entry.get("structured") or {}).get("mean_score")
        jdg = entry.get("judge") or {}
        print(f"{system:>12} | {str(struct):>10} "
              f"{str(jdg.get('mean_record_score')):>8} "
              f"{str(jdg.get('mean_flow_score')):>8} "
              f"{str(jdg.get('fabricated_fields_per_case')):>16}")
        for persona_id, stats in (entry.get("by_persona") or {}).items():
            judge_persona = (
                (summary.get("judge", {}).get("by_persona", {}) or {})
                .get(system, {})
                .get(persona_id, {})
            )
            print(f"{system:>12} |   {persona_id:>8}: "
                  f"structured={stats['mean_structured_score']} "
                  f"record={judge_persona.get('mean_record_score')} "
                  f"flow={judge_persona.get('mean_flow_score')}")
    print("Summary saved to:", config.SUMMARY_REPORT_PATH)
    print("=" * 72)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the full CIRA evaluation.")
    parser.add_argument("--only", nargs="+", choices=STAGES,
                        help="Run only these stages.")
    parser.add_argument("--skip", nargs="+", choices=STAGES,
                        help="Skip these stages.")
    parser.add_argument("--systems", nargs="+", choices=config.SYSTEMS,
                        help="Limit scoring/judging to these systems. Default: both.")
    parser.add_argument("--case", default=None, help="Restrict to one case id, e.g. 04-01")
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
    }

    # Resolve and persist the assignment ONCE, before any system runs, so all
    # three systems provably face the same patient on the same case and the
    # mapping survives in outputs/reports/persona_assignment.json.
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
        stage_summary(systems)


if __name__ == "__main__":
    main()
