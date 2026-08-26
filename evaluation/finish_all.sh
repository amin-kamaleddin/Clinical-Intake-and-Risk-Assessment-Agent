#!/bin/bash
set -o pipefail
cd "$(dirname "$0")"
PY=../venv/bin/python

echo "=== [1/5] waiting for the primary judge to finish ==="
while pgrep -f "harness.stages.run_judge" | grep -qv "$$"; do sleep 20; done
sleep 5
echo "primary judge done"

echo "=== [2/5] rebuilding summary.json (stage_summary, NOT run_all) ==="
$PY -c "from run_all import stage_summary; stage_summary(['cira','rule_based','naive_llm'], repetitions=3)" || exit 1

echo "=== [3/5] second judge (Grok) over the same transcripts ==="
mkdir -p outputs/judge_b
CIRA_JUDGE_MODEL="x-ai/grok-4-fast" CIRA_JUDGE_LABEL=b $PY -u -m harness.stages.run_judge || echo "second judge FAILED (continuing)"

echo "=== [4/5] inter-rater reliability ==="
$PY -m tools.judge_agreement || echo "agreement FAILED"

echo "=== [5/5] manuscript tables (must pass the publication gate) ==="
$PY -m tools.make_tables --out ../paper/tables && echo "TABLES OK" || echo "TABLES REFUSED (see reasons above)"

echo "ALL_STEPS_DONE"
