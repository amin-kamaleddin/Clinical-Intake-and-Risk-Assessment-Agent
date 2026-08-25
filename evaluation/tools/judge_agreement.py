"""Inter-rater reliability between the primary judge and a second judge.

No model calls. Reads two saved judge reports and compares them.

    # 1. primary judge (already run as part of the pipeline)
    python run_all.py --only judge

    # 2. second judge over the SAME transcripts, into its own namespace
    CIRA_JUDGE_MODEL="$CIRA_JUDGE_MODEL_B" CIRA_JUDGE_LABEL=b \
        python -m harness.stages.run_judge

    # 3. agreement
    python -m tools.judge_agreement

Only rows a judge actually decided are compared. Auto-resolved fields - exact
string match, boolean match, empty produced value - are settled by code before
either model sees them, so counting them would inflate agreement with rows
neither judge was asked about.
"""

from __future__ import annotations

import argparse
import json

from harness import agreement, config


def _load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _index(report: dict) -> dict:
    """(system, case, repetition) -> case record."""
    out = {}
    for system, cases in (report.get("cases") or {}).items():
        for case in cases:
            key = (
                system,
                case.get("scenario_case_id"),
                case.get("repetition", 0),
            )
            out[key] = case
    return out


def compare(report_a: dict, report_b: dict, judged_only: bool = True) -> dict:
    a_index, b_index = _index(report_a), _index(report_b)
    shared = sorted(set(a_index) & set(b_index))

    systems: dict = {}
    for system, case_id, repetition in shared:
        key = (system, case_id, repetition)
        case_a, case_b = a_index[key], b_index[key]
        block = systems.setdefault(system, {"_flow": [], "_record": [], "cases": []})

        flow_a, flow_b = case_a.get("flow_score"), case_b.get("flow_score")
        if flow_a is not None and flow_b is not None:
            block["_flow"].append((flow_a, flow_b))
            block["cases"].append(
                {
                    "case_id": case_id,
                    "repetition": repetition,
                    "flow_a": flow_a,
                    "flow_b": flow_b,
                    "difference": round(flow_b - flow_a, 4),
                }
            )

        verdicts_b = {
            row.get("ref"): row
            for row in (case_b.get("field_verdicts") or [])
        }
        for row_a in case_a.get("field_verdicts") or []:
            row_b = verdicts_b.get(row_a.get("ref"))
            if row_b is None:
                continue
            # A row settled by code carries no information about whether the
            # two MODELS agree; both simply inherit the same answer.
            if judged_only and (
                row_a.get("source") != "llm" or row_b.get("source") != "llm"
            ):
                continue
            if row_a.get("verdict") and row_b.get("verdict"):
                block["_record"].append((row_a["verdict"], row_b["verdict"]))

    out = {
        "judge_a_model": report_a.get("judge_model"),
        "judge_b_model": report_b.get("judge_model"),
        "paired_cases": len(shared),
        "judged_rows_only": judged_only,
        "systems": {},
    }
    for system, block in sorted(systems.items()):
        out["systems"][system] = {
            "flow": agreement.flow_agreement(block["_flow"]),
            "record": agreement.record_agreement(block["_record"]),
            "flow_by_case": sorted(
                block["cases"], key=lambda c: -abs(c["difference"])
            )[:10],
        }

    pooled_flow = [pair for b in systems.values() for pair in b["_flow"]]
    pooled_record = [pair for b in systems.values() for pair in b["_record"]]
    out["pooled"] = {
        "flow": agreement.flow_agreement(pooled_flow),
        "record": agreement.record_agreement(pooled_record),
    }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="b",
                        help="Label of the second judge's artifacts (default: b).")
    parser.add_argument("--all-rows", action="store_true",
                        help="Include code-resolved rows. Inflates agreement; "
                             "for diagnosis only.")
    parser.add_argument("--out", default=None, help="Write JSON here.")
    args = parser.parse_args()

    report_a = _load(config.judge_report_path(""))
    report_b = _load(config.judge_report_path(args.label))
    if not report_a:
        raise SystemExit("No primary judge report. Run: python run_all.py --only judge")
    if not report_b:
        raise SystemExit(
            f"No second-judge report at {config.judge_report_path(args.label)}.\n"
            f'Run: CIRA_JUDGE_MODEL="$CIRA_JUDGE_MODEL_B" CIRA_JUDGE_LABEL={args.label} '
            "python -m harness.stages.run_judge"
        )

    report = compare(report_a, report_b, judged_only=not args.all_rows)
    print(agreement.format_summary(report))

    pooled = report["pooled"]
    kappa = pooled["record"].get("cohens_kappa")
    print()
    print(f"  POOLED  record kappa {kappa} ({agreement.interpret_kappa(kappa)}) "
          f"over {pooled['record'].get('fields', 0)} judged fields")
    print(f"          flow spearman {pooled['flow'].get('spearman')} "
          f"over {pooled['flow'].get('cases', 0)} cases")

    path = config.JUDGE_AGREEMENT_PATH if args.out is None else __import__(
        "pathlib").Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nSaved:", path)


if __name__ == "__main__":
    main()
