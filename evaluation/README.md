# CIRA evaluation harness

One command runs the whole thing:

```bash
python run_all.py
```

That drives the live **CIRA** agent and the **rule-based** baseline over every
scenario (using the shared **patient simulator**), scores both with the same
**deterministic checks**, judges both with the same blinded **LLM-as-a-judge**,
and writes a combined summary.

## Layout

```
evaluation/
├── run_all.py                 ← the single entry point
├── cira_scenarios.json        ← ground-truth scenarios (unchanged)
├── requirements.txt
├── harness/                   ← all library + stage code
│   ├── config.py              ← ONE source of truth: paths, naming, settings, .env
│   ├── common.py              ← deterministic helpers (med parsing, transcript checks)
│   ├── patient_simulator.py   ← simulated patient (OpenRouter)
│   ├── rule_based_cira.py     ← finite-state, no-LLM baseline engine
│   ├── llm_judge.py           ← blinded rubric + weighted scoring
│   └── stages/
│       ├── run_cira.py        ← stage 1: live CIRA  → artifacts
│       ├── run_rule_based.py  ← stage 2: baseline   → artifacts
│       ├── run_naive.py       ← stage 3: naive LLM baseline (ablation) → artifacts
│       ├── score_records.py   ← deterministic scoring (all systems)
│       └── run_judge.py       ← LLM judge (all systems)
└── outputs/                   ← everything the harness produces
    ├── cira/{transcripts,records}/case_04_01.json
    ├── rule_based/{transcripts,records}/case_04_01.json
    ├── naive_llm/{transcripts,records}/case_04_01.json
    ├── judge/{cira,rule_based,naive_llm}/case_04_01.json
    └── reports/
        ├── cira_deterministic.json
        ├── rule_based_deterministic.json
        ├── naive_llm_deterministic.json
        ├── judge_comparison.json
        └── summary.json
```

### Naming (consistent everywhere)

* Every per-case file is `case_<id>.json` (e.g. `case_04_01.json`). The folder it
  sits in names its type and system, so the filename never repeats that.
* Case-id helpers live once in `harness/config.py`:
  `safe_case_id("04-01") → "04_01"`, `short_case_id("04-01") → "01"`.

## Running

```bash
python run_all.py                      # full pipeline
python run_all.py --case 04-01         # one scenario end-to-end
python run_all.py --skip cira          # no live agent? skip it
python run_all.py --only rule_based score
python run_all.py --systems rule_based # limit scoring/judging to one system
```

Each stage is also runnable on its own for debugging:

```bash
python -m harness.stages.run_cira --case 04-01
python -m harness.stages.run_rule_based
python -m harness.stages.score_records --system rule_based
python -m harness.stages.run_judge --system cira
```

Stages that need external services (the live CIRA package in `../cira`, or LLM
API keys for the simulator and judge) fail gracefully — the failure is reported
and the run continues, so a partial setup still produces whatever it can.

## Configuration

All tunables are environment variables, read once in `harness/config.py` and
loadable from `evaluation/.env` or `../cira/.env`:

| Variable | Purpose | Default |
|---|---|---|
| `OPEN_ROUTER` | OpenRouter API key (patient simulator + judge) | – |
| `OPENROUTER_BASE_URL` | OpenRouter endpoint | `https://openrouter.ai/api/v1` |
| `CIRA_PATIENT_MODEL` | patient simulator model | `openai/gpt-5.4-mini` |
| `CIRA_JUDGE_MODEL` | judge model | `google/gemini-3.1-flash-lite` |
| `CIRA_JUDGE_BASE_URL` / `CIRA_JUDGE_API_KEY` | judge endpoint / key | OpenRouter's |
| `CIRA_JUDGE_REASONING_EFFORT` | Gemini thinking level (`minimal`/`low`/`medium`/`high`/`default`) | `minimal` |
| `CIRA_EVAL_TEMPERATURE` / `CIRA_JUDGE_TEMPERATURE` | sampling temperature | `0` |
| `CIRA_JUDGE_TIMEOUT` | seconds before a stalled judge call aborts | `90` |
| `CIRA_JUDGE_MAX_RETRIES` | judge retries on transient failure | `2` |
| `CIRA_JUDGE_MAX_TOKENS` | judge output token cap | `4000` |
| `CIRA_JUDGE_MAX_WORKERS` | concurrent cases judged | `4` |
| `CIRA_MAX_TURNS_PER_SECTION` | per-section turn cap for live CIRA | `30` |
| `CIRA_NAIVE_MODEL` | naive-baseline model (defaults to CIRA's `CIRA_MODEL`) | `gpt-5.6-luna` |
| `CIRA_NAIVE_BASE_URL` / `CIRA_NAIVE_API_KEY` | naive endpoint / key | default OpenAI, like CIRA |
| `CIRA_NAIVE_REASONING_EFFORT` | naive reasoning setting | `none` |
| `CIRA_NAIVE_MAX_TURNS` | naive intake turn cap | `90` |

## Record & transcript format

* **Records** (`outputs/<system>/records/case_XX.json`) mirror the scenario
  `patient_facts` layout: the 12 intake sections as nested dicts, plus
  `case_id`, `scenario_case_id`, `safety_flag`, and `sections_completed`.
  Conversation and runtime state (LangChain `messages`, `session_id`,
  `current_section`, ...) is never written, so no messages or tool calls appear
  in a record.
* **Transcripts** (`outputs/<system>/transcripts/case_XX.json`) contain only
  real dialogue turns under `conversation` (non-empty `CIRA`/`PATIENT` text);
  empty tool-call turns and tool results are filtered out.

## What each report contains

* `<system>_deterministic.json` — per-case pass/fail on exact checks (safety flag,
  PHQ-9 Q9 → safety invariant, PHQ-9/GAD-7 totals, all sections completed,
  medication coverage, and transcript checks) plus per-metric accuracy.
* `judge_comparison.json` — per-system mean scores and subscores, plus a paired
  per-case diff (`rule_based − cira`) on the same scenarios.
* `summary.json` — the deterministic and judge summaries combined.
