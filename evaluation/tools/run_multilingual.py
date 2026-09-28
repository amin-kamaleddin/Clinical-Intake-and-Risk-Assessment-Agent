"""Run the multilingual evaluation for ONE language.

    python -m tools.run_multilingual --language "Arabic"
    python -m tools.run_multilingual --language "Mandarin Chinese" --repetitions 3
    python -m tools.run_multilingual --language Farsi --only intakes

Ten scenarios (harness/multilingual_cases.py), one language per invocation,
written into that language's own outputs tree so the frozen English result set is
untouched and serves as the control arm.

Deliberately NOT part of run_all. run_all is the 50-case publication pipeline and
its completed-run guard protects the frozen artifacts; this is a separate
experiment with a different corpus, and mixing the two is how result sets get
contaminated.

The conversation happens in the target language. The RECORD does not: CIRA stores
every saved value in English whatever the conversation language, so record
scoring, the record judge and the structured score are unchanged and directly
comparable to the English run.
"""

from __future__ import annotations

import argparse
import atexit
import os
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", required=True,
                        help='Conversation language, e.g. "Arabic", "Mandarin Chinese".')
    parser.add_argument("--repetitions", type=int, default=1,
                        help="Independent interactions per scenario (default 1).")
    parser.add_argument("--only", nargs="+", default=["intakes", "score", "judge"],
                        choices=["intakes", "score", "judge"],
                        help="Stages to run (default: all three).")
    parser.add_argument("--force-lock", action="store_true")
    args = parser.parse_args()

    # Set BEFORE importing the harness: config reads CIRA_LANGUAGE at import time
    # to decide which outputs tree to use, so importing first would pin the run
    # to English and then write it into the target language's directory.
    os.environ["CIRA_LANGUAGE"] = args.language

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from harness import config, provenance
    from harness.multilingual_cases import MULTILINGUAL_CASE_IDS
    sys.path.insert(0, str(config.CIRA_DIR))
    from core.languages import LANGUAGES

    # Refuse an unrecognised language rather than falling back to English.
    #
    # core.languages.get() falls back deliberately - that is the prompt's own
    # rule for an unsupported request. For an EXPERIMENT the same fallback is a
    # silent disaster: it would fill outputs_farsy/ with English transcripts and
    # the mislabelling would only surface when someone read them.
    if args.language not in LANGUAGES:
        print(f"\nUnknown language: {args.language!r}")
        print(f"Supported: {', '.join(LANGUAGES)}")
        print("\nAdd it to cira/core/languages.py first - a language without "
              "frequency phrases cannot administer the questionnaires.")
        raise SystemExit(1)

    if config.LANGUAGE != args.language:
        print(f"\nLanguage did not take effect: asked for {args.language!r}, "
              f"harness sees {config.LANGUAGE!r}. Refusing to run.")
        raise SystemExit(1)

    config.ensure_output_dirs()

    print("=" * 74)
    print(f"MULTILINGUAL EVALUATION - {args.language}")
    print("=" * 74)
    print(f"  cases        {len(MULTILINGUAL_CASE_IDS)}: {', '.join(MULTILINGUAL_CASE_IDS)}")
    print(f"  repetitions  {args.repetitions}")
    print(f"  outputs      {config.OUTPUTS_DIR.name}/")
    print(f"  persona seed {config.PERSONA_SEED}  (same assignment as the English run)")

    try:
        provenance.guard_completed_run(force=args.force_lock)
        run_id = provenance.new_run_id()
        provenance.acquire_lock(run_id, force=args.force_lock)
    except RuntimeError as error:
        print(f"\nREFUSING TO START: {error}\n")
        raise SystemExit(1)
    atexit.register(provenance.release_lock)

    manifest = provenance.write_manifest(run_id=run_id, repetitions=args.repetitions)
    print(f"  run_id       {manifest['run_id']}   code {manifest['code_revision']}")
    print(f"  language     {manifest['language']}")
    print(f"  temperatures {manifest['temperatures']}")
    print("=" * 74)

    if "intakes" in args.only:
        from harness.stages import run_cira
        for index, case_id in enumerate(MULTILINGUAL_CASE_IDS, start=1):
            print(f"\n[{args.language}] case {index}/{len(MULTILINGUAL_CASE_IDS)}: {case_id}")
            try:
                run_cira.run(case_filter=case_id, repetitions=args.repetitions)
            except Exception as error:  # noqa: BLE001 - one bad case must not end the run
                print(f"[{args.language}] {case_id} FAILED: {error}")

    if "score" in args.only:
        from harness.stages import score_records
        print(f"\n[{args.language}] scoring")
        score_records.run(system="cira", case_ids=MULTILINGUAL_CASE_IDS)

    if "judge" in args.only:
        from harness.stages import run_judge
        print(f"\n[{args.language}] judging")
        run_judge.run(systems=["cira"], case_ids=MULTILINGUAL_CASE_IDS)

    print(f"\n{args.language}: done. Artifacts under {config.OUTPUTS_DIR.name}/")


if __name__ == "__main__":
    main()
