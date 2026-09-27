"""Compare the multilingual runs against the English control.

    python -m tools.compare_languages
    python -m tools.compare_languages --out ../paper/tables/multilingual.md

Reads each language's own outputs tree (outputs_arabic/, outputs_farsi/, ...) and
the frozen English run (outputs/), restricting English to the SAME ten scenarios
so the control is the same corpus and not the full fifty.

WHAT IS COMPARABLE ACROSS LANGUAGES, AND WHAT IS NOT

  Comparable. These are computed from the record, which CIRA writes in English
  whatever the conversation language, or from numbers:
      structured_score, PHQ-9 / GAD-7 item accuracy
      safety flag accuracy, sensitivity, specificity
      safety-response delivery, count and latency
      record_score, fabricated fields
      section completion
      questionnaire fall-throughs

  NOT comparable. flow_score is a judgement about conversational quality made by
  a judge reading a different language each time. A lower flow score in Arabic
  may mean the intake was worse, or may mean the judge scores Arabic prose
  differently; this design cannot separate those. It is printed for completeness
  and must not be used to rank languages.

  Read fall-throughs first. A questionnaire item that fell through to the LLM did
  not use its stored ground-truth answer, so a structured score computed over
  many fall-throughs is measuring the simulator's improvisation rather than the
  intake. Zero is the only value that leaves structured_score meaning what it
  means in English.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness import config  # noqa: E402
from harness.multilingual_cases import MULTILINGUAL_CASE_IDS  # noqa: E402

sys.path.insert(0, str(config.CIRA_DIR))
from core.languages import EVALUATION_LANGUAGES  # noqa: E402


def _slug(language: str) -> str:
    return "" if language == "English" else language.lower().replace(" ", "_").replace("-", "_")


def outputs_dir(language: str) -> Path:
    slug = _slug(language)
    return config.EVALUATION_DIR / ("outputs" if not slug else f"outputs_{slug}")


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def collect(language: str) -> dict | None:
    """Per-language metrics, restricted to the ten multilingual scenarios."""
    root = outputs_dir(language)
    deterministic = _load(root / "reports" / "cira_deterministic.json")
    if not deterministic:
        return None

    wanted = set(MULTILINGUAL_CASE_IDS)
    cases = [c for c in deterministic.get("cases", [])
             if c.get("scenario_case_id") in wanted]
    if not cases:
        return None

    structured = [c["structured"]["score"] for c in cases]
    elicitation = sum(c["structured"]["failure_modes"]["elicitation_errors"]
                      for c in cases)
    complete = sum(1 for c in cases
                   if c["checks"]["all_sections_completed"]["passed"])

    # Reuse the real aggregator on the filtered cases rather than recomputing
    # accuracy here. Each per-case safety block already carries expected_flag,
    # actual_flag, is_distractor and the Q9 invariant, so a second definition of
    # "correct" in this file could only drift from the one the run used.
    from harness import safety_score as safety_score_module
    safety = safety_score_module.summarize([c["safety"] for c in cases])

    # Re-aggregated from THESE ten cases, not read from the report summary.
    #
    # score_records loads the whole scenario file, so a per-language report
    # carries all fifty cases with forty of them absent, and its summary block
    # averages over those absences. Reusing harness.safety_response.summarize
    # rather than reimplementing it keeps one definition of these metrics.
    from harness import safety_response as safety_response_module
    per_case = [c["safety_response"] for c in cases if c.get("safety_response")]
    response = (
        safety_response_module.summarize(per_case) if per_case else {}
    )
    judge = _load(root / "reports" / "judge_comparison.json") or {}
    judge_cases = [c for c in (judge.get("cases", {}).get("cira") or [])
                   if c.get("scenario_case_id") in wanted and "flow_score" in c]

    manifest = _load(root / "reports" / "run_manifest.json") or {}

    def mean(values):
        values = [v for v in values if v is not None]
        return round(sum(values) / len(values), 4) if values else None

    return {
        "language": language,
        "outputs": root.name,
        "run_id": manifest.get("run_id"),
        "code": manifest.get("code_revision"),
        "repetitions": manifest.get("repetitions"),
        "intakes": len(cases),
        "structured": mean(structured),
        "elicitation_errors": elicitation,
        "sections_complete": f"{complete}/{len(cases)}",
        "flag_accuracy": safety.get("plain_accuracy"),
        "balanced_accuracy": safety.get("safety_score"),
        "sensitivity": safety.get("sensitivity"),
        "specificity": safety.get("specificity"),
        "distractor_specificity": safety.get("distractor_specificity"),
        "missed_risk": safety.get("missed_risk_cases") or [],
        "false_alarms": safety.get("false_alarm_cases") or [],
        "response_rate": response.get("response_rate_current_risk"),
        "responses_per_case": response.get("mean_responses_per_risk_case"),
        "first_response_at": response.get("median_first_response_fraction"),
        "record_score": mean(c.get("record_score") for c in judge_cases),
        "fabricated_per_case": (
            # record_detail.fabricated_fields is the COUNT; case["fabricated"]
            # is the list of refs, and summing those gave a type error.
            round(sum((c.get("record_detail") or {}).get("fabricated_fields", 0)
                      for c in judge_cases) / len(judge_cases), 3)
            if judge_cases else None
        ),
        "flow_score": mean(c.get("flow_score") for c in judge_cases),
    }


#: Scripts that cannot appear in an English record. Latin-script leakage - a
#: French "Féminin" left untranslated - is NOT detected this way and needs a
#: reader; these four languages are detectable because they change script.
_NON_LATIN = [
    ("CJK", 0x4E00, 0x9FFF),
    ("Arabic", 0x0600, 0x06FF),
    ("Devanagari", 0x0900, 0x097F),
]


def record_language_leaks(language: str) -> dict | None:
    """Record fields left in the conversation language instead of English.

    CIRA is instructed to store every saved value in English whatever the
    conversation language, and the whole multilingual design rests on it: the
    record judge compares a produced value against English ground truth, so a
    field left in Mandarin is scored as wrong even when the intake understood it
    perfectly. Compliance is a model behaviour, not a guarantee, so it is
    measured rather than assumed - a live Mandarin intake stored gender as 女性
    while every other field came back in English.

    Proper nouns are exempt: a name or street address is kept as the patient
    gave it, so those fields are not counted.
    """
    root = outputs_dir(language)
    directory = root / "cira" / "records"
    if not directory.is_dir():
        return None

    exempt = {"name", "address", "family_doctor_name", "psychiatrist_name",
              "email", "phone_number", "emergency_contact_name"}
    leaked, total, examples = 0, 0, []
    for path in sorted(directory.glob("case_*.json")):
        record = _load(path) or {}
        for section, fields in record.items():
            if not isinstance(fields, dict):
                continue
            for field, value in fields.items():
                if field in exempt or not isinstance(value, str) or not value.strip():
                    continue
                total += 1
                hit = next(
                    (name for name, low, high in _NON_LATIN
                     if any(low <= ord(ch) <= high for ch in value)),
                    None,
                )
                if hit:
                    leaked += 1
                    if len(examples) < 6:
                        examples.append(f"{section}.{field}={value[:28]}")
    return {
        "leaked_fields": leaked,
        "text_fields": total,
        "rate": round(leaked / total, 4) if total else None,
        "examples": examples,
    }


def fall_throughs(language: str) -> int | None:
    """Questionnaire items that lost their ground-truth answer, from transcripts.

    Counted from the saved artifacts rather than a log, so it survives the log
    being deleted and can be recomputed at any time.
    """
    root = outputs_dir(language)
    directory = root / "cira" / "transcripts"
    if not directory.is_dir():
        return None
    total = 0
    for path in sorted(directory.glob("case_*.json")):
        data = _load(path) or {}
        behaviour = data.get("patient_behaviour") or {}
        total += int(behaviour.get("questionnaire_fall_throughs") or 0)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    rows = []
    for language in EVALUATION_LANGUAGES:
        row = collect(language)
        if row is None:
            print(f"  (no results yet for {language} - {outputs_dir(language).name}/)")
            continue
        row["fall_throughs"] = fall_throughs(language)
        row["leaks"] = record_language_leaks(language)
        rows.append(row)

    if not rows:
        raise SystemExit("No results found. Run tools.run_multilingual first.")

    lines = []
    add = lines.append
    add(f"# Multilingual evaluation - {len(MULTILINGUAL_CASE_IDS)} scenarios per language\n")
    add(f"Cases: {', '.join(MULTILINGUAL_CASE_IDS)}\n")

    add("\n## Comparable across languages\n")
    add("| language | intakes | structured | elicit. | fall-through | sections |")
    add("|---|---|---|---|---|---|")
    for r in rows:
        add(f"| {r['language']} | {r['intakes']} | {r['structured']} | "
            f"{r['elicitation_errors']} | {r['fall_throughs']} | "
            f"{r['sections_complete']} |")

    add("\n### Safety\n")
    add("Read `missed` first: a missed risk case is the only failure this system "
        "must never produce. Sensitivity is structurally protected in every "
        "language by the PHQ-9 Q9 rule, which acts on the saved numeric score, "
        "so a miss here would mean the questionnaire itself was not administered. "
        "With three risk cases per language, sensitivity moves in steps of 1/3.\n")
    add("| language | balanced acc | sens | spec | distractor spec | missed | false alarm |")
    add("|---|---|---|---|---|---|---|")
    for r in rows:
        add(f"| {r['language']} | {r['balanced_accuracy']} | {r['sensitivity']} | "
            f"{r['specificity']} | {r['distractor_specificity']} | "
            f"{', '.join(r['missed_risk']) or 'none'} | "
            f"{', '.join(r['false_alarms']) or 'none'} |")

    add("\n## Record-language compliance\n")
    add("Every value should be stored in English whatever the conversation "
        "language, because the record judge compares it against English ground "
        "truth. Latin-script leakage (a French answer left in French) is not "
        "detectable this way and needs a reader.\n")
    add("| language | leaked fields | text fields | rate | examples |")
    add("|---|---|---|---|---|")
    for r in rows:
        leaks = r.get("leaks") or {}
        add(f"| {r['language']} | {leaks.get('leaked_fields')} | "
            f"{leaks.get('text_fields')} | {leaks.get('rate')} | "
            f"{'; '.join(leaks.get('examples') or []) or '-'} |")

    add("\n## Safety response (what the patient was actually told)\n")
    add("| language | response rate | per case | first response at |")
    add("|---|---|---|---|")
    for r in rows:
        add(f"| {r['language']} | {r['response_rate']} | "
            f"{r['responses_per_case']} | {r['first_response_at']} |")

    add("\n## Record fidelity\n")
    add("| language | record score | fabricated/case |")
    add("|---|---|---|")
    for r in rows:
        add(f"| {r['language']} | {r['record_score']} | {r['fabricated_per_case']} |")

    add("\n## Flow - NOT comparable across languages\n")
    add("A different judge pass reads a different language in each row. A lower "
        "score may mean a worse intake or may mean the judge scores that "
        "language's prose differently, and this design cannot separate the two. "
        "Do not rank languages on it.\n")
    add("| language | flow score |")
    add("|---|---|")
    for r in rows:
        add(f"| {r['language']} | {r['flow_score']} |")

    add("\n## Provenance\n")
    add("| language | outputs | run_id | code | reps |")
    add("|---|---|---|---|---|")
    for r in rows:
        add(f"| {r['language']} | {r['outputs']}/ | {r['run_id']} | {r['code']} | {r['repetitions']} |")

    document = "\n".join(lines) + "\n"
    print(document)
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(document, encoding="utf-8")
        print("Wrote", path)


if __name__ == "__main__":
    main()
