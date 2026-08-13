

from __future__ import annotations

import json

from harness import config, stats


def _load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def print_intervals() -> bool:
    """Print every interval and paired difference. Returns False if no data.

    Importable so ``run_all.py`` can print the same block at the end of a run
    without duplicating the formatting, and so it can be re-printed later from
    the saved reports without re-running anything.
    """
    print("=" * 78)
    print("DETERMINISTIC METRICS — 95% CI")
    print("=" * 78)
    print(f"{'system':>12} | {'structured':>22} | {'safety (case acc)':>22}")
    print("-" * 66)

    for system in config.SYSTEMS:
        report = _load(config.REPORTS_DIR / f"{system}_deterministic.json")
        if not report:
            continue
        unc = (report.get("summary") or {}).get("uncertainty") or {}
        print(f"{system:>12} | {stats.format_ci(unc.get('structured_score')):>22} | "
              f"{stats.format_ci(unc.get('safety_case_accuracy')):>22}")

    print(f"\n{'system':>12} | {'sensitivity':>22} | {'specificity':>22}")
    print("-" * 66)
    for system in config.SYSTEMS:
        report = _load(config.REPORTS_DIR / f"{system}_deterministic.json")
        if not report:
            continue
        unc = (report.get("summary") or {}).get("uncertainty") or {}
        print(f"{system:>12} | {stats.format_ci(unc.get('safety_sensitivity')):>22} | "
              f"{stats.format_ci(unc.get('safety_specificity')):>22}")

    judge = _load(config.JUDGE_REPORT_PATH)
    if not judge:
        print("\nNo judge report found.")
        return True

    print()
    print("=" * 78)
    print("JUDGED METRICS — 95% CI")
    print("=" * 78)
    print(f"{'system':>12} | {'contested record':>22} | {'flow':>22} | "
          f"{'fabricated/case':>20}")
    print("-" * 84)
    for system, unc in (judge.get("uncertainty") or {}).items():
        print(f"{system:>12} | "
              f"{stats.format_ci(unc.get('record_score_contested')):>22} | "
              f"{stats.format_ci(unc.get('flow_score')):>22} | "
              f"{stats.format_ci(unc.get('fabricated_fields')):>20}")

    print("\nRUN-TO-RUN RANGE ON THE SAME SCENARIO")
    print("  (if this exceeds the gap between two systems, the gap is not a result)")
    print("-" * 78)
    for system, unc in (judge.get("uncertainty") or {}).items():
        flow = unc.get("flow_variability") or {}
        record = unc.get("record_variability") or {}
        print(f"  {system:>12}  flow median {flow.get('median_within_scenario_range')} "
              f"max {flow.get('max_within_scenario_range')}   |   "
              f"record median {record.get('median_within_scenario_range')} "
              f"max {record.get('max_within_scenario_range')}")

    print()
    print("=" * 78)
    print("PAIRED DIFFERENCES  (* = 95% CI excludes zero; the claim test)")
    print("=" * 78)
    for pair, metrics in (judge.get("pairwise_differences") or {}).items():
        for name in ("record_score_contested", "flow_score", "fabricated_fields"):
            result = metrics.get(name) or {}
            print(f"  {pair:<26} {name:<24} {stats.format_difference(result)}")
        print()

    print("Overlapping individual intervals do NOT mean a difference is zero -")
    print("read the paired row, not the two CIs above it.")
    return True


def main() -> None:
    print_intervals()


if __name__ == "__main__":
    main()