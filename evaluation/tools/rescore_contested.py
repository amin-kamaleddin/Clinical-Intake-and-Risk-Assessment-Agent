

from __future__ import annotations

import argparse
import json

from harness import config
from harness import record_check
from harness.stages.run_judge import (
    build_shared_contested_refs,
    score_over_shared_refs,
)


def _mean(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 4) if values else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the corrected numbers without rewriting the report.")
    args = parser.parse_args()

    report = json.loads(config.JUDGE_REPORT_PATH.read_text(encoding="utf-8"))
    all_cases = report["cases"]

    shared_refs = build_shared_contested_refs(all_cases)
    total_shared = sum(len(refs) for refs in shared_refs.values())
    print(f"Shared contested field set: {total_shared} refs across "
          f"{len(shared_refs)} cases "
          f"({round(total_shared / max(len(shared_refs), 1), 1)} per case)\n")

    print(f"{'system':>12} | {'own-set':>8} {'own n':>6} | "
          f"{'SHARED':>8} {'n':>5} | {'overall':>8}")
    print("-" * 62)

    for system, cases in all_cases.items():
        ok = [c for c in cases if c.get("status") == "OK"]
        for case in ok:
            case["contested_shared"] = score_over_shared_refs(
                case, shared_refs.get(case["scenario_case_id"], set())
            )

        summary = report["systems"][system]
        shared_score = _mean(
            (c.get("contested_shared") or {}).get("score") for c in ok
        )
        shared_n = _mean(
            (c.get("contested_shared") or {}).get("fields") for c in ok
        )
        own_score = summary.get("mean_record_score_contested_own",
                                summary.get("mean_record_score_contested"))
        own_n = summary.get("mean_fields_contested_own",
                            summary.get("mean_fields_contested"))

        summary["mean_record_score_contested_own"] = own_score
        summary["mean_fields_contested_own"] = own_n
        summary["mean_record_score_contested"] = shared_score
        summary["mean_fields_contested"] = shared_n

        print(f"{system:>12} | {str(own_score):>8} {str(own_n):>6} | "
              f"{str(shared_score):>8} {str(shared_n):>5} | "
              f"{str(summary['mean_record_score']):>8}")

    # Persona breakdown on the shared set too.
    for system, cases in all_cases.items():
        ok = [c for c in cases if c.get("status") == "OK"]
        for persona_id, stats in (report.get("by_persona", {})
                                  .get(system, {}) or {}).items():
            subset = [c for c in ok if c.get("persona_id") == persona_id]
            stats["mean_record_score_contested"] = _mean(
                (c.get("contested_shared") or {}).get("score") for c in subset
            )

    report.setdefault("evaluation_design", {})[
        "contested_scored_over_shared_field_set"
    ] = True

    if args.dry_run:
        print("\n(dry run - report not modified)")
        return

    config.JUDGE_REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nUpdated {config.JUDGE_REPORT_PATH}")
    print("Run `python run_all.py --only summary` to refresh summary.json.")


if __name__ == "__main__":
    main()
