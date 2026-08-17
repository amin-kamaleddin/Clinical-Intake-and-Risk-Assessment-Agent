"""Generate manuscript tables directly from the run artifacts.

Numbers copied by hand into a manuscript drift from the run that produced them,
and nothing catches it. These tables are generated from
``outputs/reports/`` and stamped with the ``run_id``, code revision and prompt
hashes of that run, so a table in the paper can always be traced back to the
artifacts it came from — and regenerating it after a re-run is one command.

    python -m tools.make_tables                 # markdown to stdout
    python -m tools.make_tables --format latex
    python -m tools.make_tables --out ../paper/tables

Nothing here recomputes a metric. Every value is read from the reports, so the
tables cannot disagree with the evaluation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from harness import config, stats


def _load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _ci(entry) -> str:
    return stats.format_ci(entry) if entry else "n/a"


def _fmt(value, digits=3) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def collect() -> dict:
    """Everything the tables need, read from the saved reports."""
    summary = _load(config.SUMMARY_REPORT_PATH) or {}
    judge = _load(config.JUDGE_REPORT_PATH) or {}
    deterministic = {
        system: _load(config.REPORTS_DIR / f"{system}_deterministic.json")
        for system in config.SYSTEMS
    }
    return {"summary": summary, "judge": judge, "deterministic": deterministic}


def table_main(data: dict) -> list[list[str]]:
    """Primary results: one row per system, estimate with 95% CI."""
    rows = [["System", "Safety", "Structured", "Record (contested)",
             "Flow", "Fabricated/case"]]
    judge_unc = data["judge"].get("uncertainty") or {}

    for system in config.SYSTEMS:
        report = data["deterministic"].get(system)
        if not report:
            continue
        det = report.get("summary") or {}
        unc = det.get("uncertainty") or {}
        ju = judge_unc.get(system) or {}
        rows.append([
            system,
            _ci(unc.get("safety_case_accuracy")),
            _ci(unc.get("structured_score")),
            _ci(ju.get("record_score_contested")),
            _ci(ju.get("flow_score")),
            _ci(ju.get("fabricated_fields")),
        ])
    return rows


def table_paired(data: dict) -> list[list[str]]:
    """Paired differences — the only rows that license a comparative claim."""
    rows = [["Comparison", "Metric", "Difference [95% CI]", "Significant"]]
    for pair, metrics in (data["judge"].get("pairwise_differences") or {}).items():
        for name in ("record_score_contested", "flow_score", "fabricated_fields"):
            result = metrics.get(name) or {}
            if result.get("difference") is None:
                continue
            rows.append([
                pair, name,
                f"{result['difference']:+.3f} "
                f"[{result['ci_low']:+.3f}, {result['ci_high']:+.3f}]",
                "yes" if result.get("excludes_zero") else "no",
            ])
    return rows


def table_safety(data: dict) -> list[list[str]]:
    """Safety detail: the two error directions are never averaged together."""
    rows = [["System", "Sensitivity", "Specificity", "Distractor spec.",
             "Missed risk", "False alarms"]]
    for system in config.SYSTEMS:
        report = data["deterministic"].get(system)
        if not report:
            continue
        det = report.get("summary") or {}
        safety = det.get("safety") or {}
        unc = det.get("uncertainty") or {}
        rows.append([
            system,
            _ci(unc.get("safety_sensitivity")),
            _ci(unc.get("safety_specificity")),
            _fmt(safety.get("distractor_specificity")),
            ", ".join(safety.get("missed_risk_cases") or []) or "none",
            ", ".join(safety.get("false_alarm_cases") or []) or "none",
        ])
    return rows


def table_persona(data: dict) -> list[list[str]]:
    """Degradation across patient difficulty."""
    rows = [["System", "Persona", "Structured", "Record", "Flow"]]
    judge_persona = (data["judge"].get("by_persona") or {})
    for system in config.SYSTEMS:
        report = data["deterministic"].get(system)
        if not report:
            continue
        by_persona = (report.get("summary") or {}).get("by_persona") or {}
        for persona_id, entry in by_persona.items():
            ju = (judge_persona.get(system) or {}).get(persona_id) or {}
            rows.append([
                system, persona_id,
                _fmt(entry.get("mean_structured_score")),
                _fmt(ju.get("mean_record_score")),
                _fmt(ju.get("mean_flow_score")),
            ])
    return rows


def table_budget(data: dict) -> list[list[str]]:
    """Interaction cost — qualifies every comparison above it."""
    rows = [["System", "Median turns", "Median words", "Turn ratio"]]
    ratios = (data["summary"].get("budget_comparison") or {}).get(
        "turn_ratio_vs_reference", {}
    )
    for system in config.SYSTEMS:
        report = data["deterministic"].get(system)
        if not report:
            continue
        budget = (report.get("summary") or {}).get("budget") or {}
        if not budget.get("cases"):
            continue
        rows.append([
            system,
            _fmt(budget.get("median_total_turns"), 0),
            _fmt(budget.get("median_total_words"), 0),
            _fmt(ratios.get(system), 2),
        ])
    return rows


def to_markdown(title: str, rows: list[list[str]]) -> str:
    if len(rows) < 2:
        return f"### {title}\n\n_(no data)_\n"
    header, *body = rows
    out = [f"### {title}", "",
           "| " + " | ".join(header) + " |",
           "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(out) + "\n"


def to_latex(title: str, rows: list[list[str]]) -> str:
    if len(rows) < 2:
        return ""
    header, *body = rows
    spec = "l" * len(header)
    escape = lambda t: (t.replace("_", r"\_").replace("%", r"\%")
                        .replace("&", r"\&").replace("[", "{[}").replace("]", "{]}"))
    out = [r"\begin{table}[t]", r"\centering",
           rf"\caption{{{escape(title)}}}",
           rf"\begin{{tabular}}{{{spec}}}", r"\hline",
           " & ".join(escape(h) for h in header) + r" \\", r"\hline"]
    out += [" & ".join(escape(c) for c in r) + r" \\" for r in body]
    out += [r"\hline", r"\end{tabular}", r"\end{table}", ""]
    return "\n".join(out)


TABLES = [
    ("Primary results (estimate [95% CI])", table_main),
    ("Paired differences", table_paired),
    ("Safety detail", table_safety),
    ("Performance by patient difficulty", table_persona),
    ("Interaction budget", table_budget),
]


def provenance_note(data: dict) -> str:
    prov = data["summary"].get("provenance") or {}
    models = prov.get("models") or {}
    inputs = prov.get("inputs") or {}
    reps = data["summary"].get("repetitions")
    return (
        f"Generated from run `{prov.get('run_id')}` "
        f"(code `{prov.get('code_revision')}`), "
        f"{reps} repetition(s) per scenario.\n\n"
        f"Models — CIRA: `{models.get('cira')}`, "
        f"patient: `{models.get('patient_simulator')}`, "
        f"naive: `{models.get('naive_llm')}`, "
        f"judge: `{models.get('judge')}`.\n\n"
        f"Scenario file sha256 `{inputs.get('scenario_sha256')}`; "
        f"prompt hashes `{inputs.get('prompt_sha256')}`.\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("markdown", "latex"), default="markdown")
    parser.add_argument("--out", default=None, help="Directory to write files into.")
    args = parser.parse_args()

    data = collect()
    if not data["summary"]:
        print("No summary.json found. Run the evaluation first.")
        return

    render = to_markdown if args.format == "markdown" else to_latex
    parts = [render(title, builder(data)) for title, builder in TABLES]
    document = (
        "# Manuscript tables\n\n" + provenance_note(data) + "\n"
        + "\n".join(parts)
        + "\nPaired differences are the basis for comparative claims; a "
          "difference whose interval includes zero is not evidence of "
          "superiority. Interaction budgets are not equalised across arms, so "
          "completeness and flow differences are confounded with effort.\n"
    )

    if args.out:
        directory = Path(args.out)
        directory.mkdir(parents=True, exist_ok=True)
        suffix = "md" if args.format == "markdown" else "tex"
        path = directory / f"tables.{suffix}"
        path.write_text(document, encoding="utf-8")
        print("Wrote", path)
    else:
        print(document)


if __name__ == "__main__":
    main()
