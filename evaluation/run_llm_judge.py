"""Run the CIRA LLM judge across saved evaluation cases."""

from __future__ import annotations

import json
from pathlib import Path

from llm_judge import CIRAJudge, save_judge_result


PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVALUATION_DIR = PROJECT_ROOT / "evaluation"
SCENARIO_FILE = EVALUATION_DIR / "cira_scenarios.json"
TRANSCRIPT_DIR = EVALUATION_DIR / "transcripts"
RECORD_DIR = EVALUATION_DIR / "records"
JUDGE_DIR = EVALUATION_DIR / "judge_results"
SUMMARY_FILE = EVALUATION_DIR / "results" / "llm_judge_report.json"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def find_transcript(scenario_case_id: str) -> Path:
    expected = TRANSCRIPT_DIR / f"case_{scenario_case_id.replace('-', '_')}.json"
    if not expected.exists():
        raise FileNotFoundError(f"Transcript not found: {expected}")
    return expected


def find_latest_record(scenario_case_id: str) -> Path:
    matches = list(RECORD_DIR.glob(f"evaluation_{scenario_case_id}_*.json"))
    if not matches:
        raise FileNotFoundError(
            f"No produced record found for {scenario_case_id} in {RECORD_DIR}"
        )
    return max(matches, key=lambda path: path.stat().st_mtime)


def main() -> None:
    scenarios = load_json(SCENARIO_FILE)
    judge = CIRAJudge()
    report = []

    for scenario in scenarios:
        scenario_case_id = scenario["case_id"]
        case_id = scenario_case_id.split("-")[-1]
        print(f"Judging {scenario_case_id}...")

        try:
            transcript_path = find_transcript(scenario_case_id)
            record_path = find_latest_record(scenario_case_id)

            transcript = load_json(transcript_path)
            produced_record = load_json(record_path)

            result = judge.evaluate(
                scenario=scenario,
                transcript=transcript,
                produced_record=produced_record,
            )

            result_path = JUDGE_DIR / f"judge_{scenario_case_id.replace('-', '_')}.json"
            save_judge_result(result, result_path)

            report.append({
                **result.model_dump(),
                "transcript_file": str(transcript_path),
                "record_file": str(record_path),
                "judge_result_file": str(result_path),
                "status": "OK",
            })

            print(
                f"  conversation={result.conversation_quality_score:.3f} | "
                f"record={result.record_accuracy_score:.3f}"
            )
        except Exception as error:
            print(f"  ERROR: {error}")
            report.append({
                "case_id": case_id,
                "scenario_case_id": scenario_case_id,
                "status": "ERROR",
                "error": str(error),
            })

    successful = [item for item in report if item["status"] == "OK"]
    if successful:
        mean_conversation = sum(
            item["conversation_quality_score"] for item in successful
        ) / len(successful)
        mean_record = sum(
            item["record_accuracy_score"] for item in successful
        ) / len(successful)
    else:
        mean_conversation = None
        mean_record = None

    summary = {
        "judge_model": judge.model_name,
        "cases": report,
        "summary": {
            "evaluated_cases": len(successful),
            "error_cases": len(report) - len(successful),
            "mean_conversation_quality_score": mean_conversation,
            "mean_record_accuracy_score": mean_record,
        },
    }

    SUMMARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_FILE.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nSaved report to: {SUMMARY_FILE}")


if __name__ == "__main__":
    main()
