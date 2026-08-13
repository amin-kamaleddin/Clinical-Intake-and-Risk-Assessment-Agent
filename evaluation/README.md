# CIRA evaluation harness

One command runs everything:

```bash
python run_all.py
```

Three systems are driven over twelve scenarios using the same simulated patient,
scored with the same deterministic checks, judged by the same blinded LLM judge,
and combined into one summary.

| system | what it is |
|---|---|
| `cira` | the live LangGraph intake agent |
| `rule_based` | a deterministic finite-state intake. No LLM at any point. |
| `naive_llm` | a **prompt-only LLM architecture ablation** — one clinical intake prompt plus a structured-extraction call. Not an unconfigured or "generic" model; describing it that way overstates the contrast. |

---

## The metrics

Every system gets four numbers per case. One rule decides where each check
goes: **does an exact expected value exist?** If yes, code computes it. If it
needs semantic judgement, the LLM does.

| metric | source | measures |
|---|---|---|
| `safety_score` | **code** | risk-flag sensitivity and specificity |
| `structured_score` | **code** | PHQ-9 and GAD-7 items and totals |
| `record_score` | LLM verdicts, aggregated by code | free-text capture, paraphrase-tolerant |
| `flow_score` | LLM, holistic | interviewing quality |

Plus `fabricated_fields_per_case`, counted in code.

They do not overlap. The record judge never sees `phq9`/`gad7` — those sections
are stripped before its payload is built — and the flow judge never sees the
record.

### Reading the output

`run_all.py` prints three blocks, in increasing order of what they let you claim:

1. **PRIMARY METRICS** — point estimates per system.
2. **BY PATIENT DIFFICULTY** — the same metrics split clear / moderate / confused.
3. **95% CIs and PAIRED DIFFERENCES** — printed automatically at the end of the
   summary stage.

**Read the paired row, not the point estimates.** A gap smaller than its own
interval is not a result, and two overlapping individual intervals do *not* mean
the difference is zero. `*` marks a difference whose 95% CI excludes zero; that
is the only basis for claiming one system beats another.

To re-print the intervals later from saved reports, with no API calls and no
re-running:

```bash
python -m tools.show_intervals
```

The numbers are computed when the reports are built, so they already live in
`judge_comparison.json`, `<system>_deterministic.json` and `summary.json` — this
only formats them.

### `safety_score` — reported separately, on purpose

Safety is one check in twenty inside `structured_score`, so a system that
answers every questionnaire item perfectly and misses **every** real risk case
still scores ~0.96 there. Plain flag accuracy is no better: with 7 negative and
5 positive scenarios, never raising the flag scores 0.583 — which reads like a
middling result rather than total failure of the function that matters most.

The headline is **balanced accuracy**, the mean of sensitivity and specificity.
Never flagging scores 0.5; always flagging also scores 0.5. It cannot be gamed
from either direction.

The two error directions are never averaged together:

* **`missed_risk_cases`** — patients at current risk whose flag was not raised,
  listed by case id. Clinically the worst output the system can produce.
* **`false_alarm_cases`** — flags on patients not at risk. Real, but far less
  severe: clinician time and, at volume, alarm fatigue.
* **`critical_failures`** — misses plus PHQ-9-Q9 invariant violations. Read this
  number first.

**`distractor_specificity`** covers only the scenarios built to be mistaken for
risk — a maternal uncle who died by suicide, historical non-suicidal
self-injury. Flagging those is the characteristic failure of a keyword matcher,
and avoiding them is the characteristic strength of a system that reasons about
subject, timeframe and polarity, so it is the interesting number for a paper.

### `structured_score` — code only

The mean of 20 binary checks: 9 PHQ-9 items, 7 GAD-7 items, 2 totals, the safety
flag, and the PHQ-9-Q9 → safety invariant. Unweighted on purpose; any weighting
here would be invented.

**Item level, not total level.** Totals alone are lossy: one item scored +1 and
another −1 gives a correct total from a broken intake.

Two failure modes are separated in the report:

* **elicitation errors** — a recorded item disagrees with ground truth. The
  system misheard, or guessed a score off a vague answer instead of re-asking.
* **arithmetic errors** — the items are right but the total is not their sum.

### `record_score` — code enumerates, LLM verdicts, code aggregates

1. `harness/record_check.py` walks `patient_facts` and the produced record in
   parallel and emits one row per checkable fact. Fields the scenario leaves
   null are dropped — they are not ground truth. Repeatable fields are split per
   entry, so capturing 1 of 3 medications cannot score the same as 3 of 3.
2. Rows needing no judgement are **auto-resolved without the model**: exact
   match, boolean match, empty produced value.
3. The LLM sees only genuinely ambiguous rows and returns a **categorical**
   verdict — `match` / `partial` / `missing` / `contradicted`. Models are poorly
   calibrated on continuous scores and reliable on categories, so this reruns
   far more consistently than a float would.
4. Code turns verdicts into the number: `match` 1.0, `partial` 0.5, rest 0.

Wording is explicitly not scored. `"Sertraline; 50 mg each morning"` and
`"Takes 50mg sertraline every morning"` are a `match`, with worked examples in
the rubric.

**Contested, and why it must be shared.** About 45% of the fields per case are
free — eight `substance_use` answers that are usually "Never", twelve booleans —
so the overall score is diluted and a state machine can tie a full agent.
`record_score_contested` covers only rows a judge had to decide.

Computing that per system makes it **uncomparable**: a system writing
verbatim-correct values auto-resolves its own easy wins out of its own
denominator and is then scored on the hard residue. On a real run that produced
12.1 contested fields per case for one system against 21.8 for another, from an
identical pool — and inverted the ranking. The reported number is therefore
scored over the **union** of contested refs: if any system needed a judgement on
a field, all systems are scored on that field. Same exam for everyone.

`mean_record_score_contested_own` is retained for comparison. Do not rank on it.

**Fabrication is reported, not penalised.** Fields the record filled where the
scenario has no ground truth are counted as `fabricated_fields_per_case`. Since
the patient simulator is prompt-bound never to invent, anything there is
unsupported by construction. Keeping it out of `record_score` means a system
cannot lose points twice for one bad field, and fabrication stands as its own
metric — usually the more interesting comparison.

A verdict the model fails to return is **counted and excluded**, never defaulted
to a pass or a fail. Watch `unjudged_fields_total`; it should be zero.

### `flow_score` — one holistic number with anchors

Transcript, persona and scenario requirements go in; one 0–1 score, a short
summary and any issues come out. No subscores, no weight vector. Anchors are
written out at six levels so the number means something across runs.

The persona matters here: with a `confused` patient, **recovery and redirection
are the target behaviours** and their absence is a real failure. Extra turns
spent recovering are explicitly not repetition.

### `status`

`PASS` means **structured perfect AND safety flag correct**. It deliberately
excludes the process checks, which are heuristics — `medication_coverage` is a
substring match, and duplicate-question detection overlaps what the flow judge
already scores. Gating `PASS` on those once produced 0/12 for a system scoring
1.000 structured on every case.

Process checks remain in the reports as diagnostics and print only when one is
below 1.0.

---

## Patient personas

Every scenario runs against one of three communication styles. The persona
changes **how** the patient talks; never **what** they know.

| persona | behaviour | temp | defer prob / per item / per instrument | hedge prob / per section |
|---|---|---|---|---|
| `clear` | literal, one clean pass. Control condition. | 0.0 | 0 / 0 / 0 | 0.0 / 0 |
| `moderate` | hedges, bundles facts, drifts one step off-topic | 0.4 | 0.35 / 1 / 2 | 0.25 / 2 |
| `confused` | rambles, misreads questions, asks for repeats | 0.8 | 0.80 / 2 / 5 | 0.50 / 4 |

### The ground-truth invariant

A persona may hedge, stall, digress, or describe something loosely — but any
concrete detail it finally states matches `patient_facts` exactly, and it never
asserts a detail that contradicts them. Otherwise record scoring would be
measuring the simulator's improvisation rather than the intake system.

The same rule governs PHQ-9/GAD-7. Hard personas **defer** an item — reply with
something non-committal so the interviewer must re-ask or re-explain the scale —
but the answer they eventually give is the exact stored frequency phrase.
Deferral lines carry no numbers on purpose: an ambiguous reply forces a re-ask,
whereas "maybe three days a week" would invite a guess that ground truth cannot
adjudicate.

Deferral is bounded per item and per instrument; free-text hedging is bounded
per section and never occurs on consecutive turns, so one good follow-up always
reaches the real answer.

### Seeded assignment

```bash
python -m harness.personas                     # show the current assignment
python -m harness.personas --seed 7            # a different draw
python run_all.py --persona-seed 7
python run_all.py --persona confused           # stress ablation
```

Two guarantees, both tested: the assignment is computed over **every** case id
in the scenario file and then filtered, so `--case 04-01` gets the same persona
it would in a full run; and all three systems derive it identically, so
comparisons stay paired.

Default strategy is `balanced` — equal counts, shuffled, so 12 cases give
exactly 4/4/4.

---

## Provenance and reproducibility

Every run writes `outputs/reports/run_manifest.json` **before anything else
executes**, and stamps its `run_id` into every artifact it produces.

It records the run id, git revision (marked `-dirty` when the tree is modified),
Python version and platform, every model name, the endpoints, the persona seed
and strategy, and SHA-256 hashes of the scenario file and of each prompt file.

**Attribution** — a committed number can be traced to the configuration that
produced it, and a hash changing between runs is proof the inputs changed.
**Contamination detection** — `check_artifact_freshness` reports any artifact
written by a different run, and the warning appears on the console and in
`summary.json`.

Nothing blocks a run: rescoring without re-running the agents is a legitimate
workflow. The point is that mixing runs can no longer happen invisibly.

All report paths are **relative to `evaluation/`**; absolute developer paths are
not reproducible on another machine.

---

## Blinding

The judge cannot tell which system produced what:

* the `system` key is excluded from both judge payloads
* speaker labels are rewritten (`CIRA` → `INTERVIEWER`)
* system names are redacted from message text and from produced field values —
  CIRA introduces itself by name in its opening line, which on its own defeated
  the blinding

The record judge never sees the transcript; the flow judge never sees the
record. A failure in one cannot contaminate the other.

---

## Repetitions and uncertainty

One interaction per scenario is a single realisation of a stochastic process. A
difference like 0.9308 vs 0.9285 is then uninterpretable — it could be a real
effect or one lucky sample. Repeating each scenario independently turns that
into a distribution.

```bash
python run_all.py --repetitions 20        # or CIRA_REPETITIONS=20
```

Repetition 0 keeps the original filename (`case_04_01.json`); later repetitions
add `_r01`, `_r02`. A single-run evaluation therefore produces byte-identical
paths to before repetitions existed, and older output sets still score.

### What varies, and what does not

Only the **repetition index** enters the patient seed. The same
`(scenario, repetition)` produces the same patient for all three systems, so at
repetition 3 every system faces an identical patient. Personas stay fixed per
scenario. Variance comes from model sampling, not from a different patient.

### Cluster bootstrap

Repetitions of the same scenario are **not** independent — 04-04 is harder than
04-02 for every system in every repetition. Treating 12 scenarios × 20
repetitions as 240 independent draws would understate the interval.

The bootstrap resamples **scenarios first, then repetitions within them**, so
both sources of uncertainty propagate: which patients we happened to write, and
how variable a system is on a given patient. Intervals are percentile-based
rather than normal, because these metrics are bounded in [0, 1] and often sit
near a boundary where a normal interval can imply impossible values.

Proportions over a handful of cases (safety sensitivity, specificity) use a
**Wilson** interval. With 5 positive cases and 5 successes the normal interval
is [1.0, 1.0], which asserts a certainty a 5-case sample cannot support; Wilson
gives [0.566, 1.000].

### Paired differences are the claim test

Every system sees the same scenarios and the same patients, so comparing two
independent intervals throws that away and is needlessly conservative —
**overlapping intervals do not imply the difference is indistinguishable from
zero.** The paired bootstrap resamples the same scenarios for both systems and
takes the difference within each draw, so scenario difficulty cancels.

```
PAIRED DIFFERENCES (* = 95% CI excludes zero)
  cira - rule_based   record_score_contested   +0.006 [+0.000, +0.011]  *
  cira - rule_based   flow_score               +0.009 [+0.002, +0.016]  *
  cira - rule_based   fabricated_fields        -0.367 [-0.517, -0.233]  *
```

`excludes_zero` is the only basis for claiming one system beats another. If it
is false, report the systems as comparable.

### Run-to-run variability

`structured_variability` and `flow_variability` report the range a system spans
on the **same** scenario across repetitions. If that range is wider than the gap
between two systems, the gap is not a result. It is reported rather than
footnoted, because it is the number that justifies running repetitions at all.

### Cost

Cost scales linearly: 20 repetitions is 20× the API calls and wall-clock time
(720 intakes plus ~1,440 judge calls for three systems over twelve scenarios).
Validate the pipeline with `--repetitions 3` before committing to a full run.

**There is no resume.** Artifacts are written per section and survive a crash,
but re-running starts from scenario 1, repetition 0 and overwrites everything.
The loop is `for repetition: for scenario:`, so a run that dies part-way leaves
whole completed repetitions on disk — back up `outputs/` between batches, or run
repetitions as separate invocations, if a 20-hour run is at risk of interruption.

Scoring and judging are cheap and re-runnable: if the run fails during those
stages, `--only score judge summary` costs no intakes.

---

## Statistical caveats

With `--repetitions 1` (the default) there are no usable intervals: every
metric is a single realisation, and differences of a few thousandths are not
evidence of superiority. Run repetitions before making comparative claims.

Even with repetitions, some limits are structural. Twelve scenarios is a small
sample: safety specificity moves in steps of 1/7 ≈ 0.14, so one false alarm is
the entire difference between 0.857 and 1.0, and no number of repetitions
changes that — repetitions reduce sampling variance, not scenario coverage.
There is also one judge model and one judge pass; sensitivity to the choice of
judge is not measured.

`flow_score` is the noisiest metric. In practice the same system on the same
scenario has varied by ~0.15 between repetitions, which is larger than some
between-system gaps. Check `flow_variability` before quoting a flow comparison;
that variance is in the judge, not the systems (record variability on the same
data is roughly an order of magnitude smaller), so repeated *judge passes* on
existing transcripts are a cheaper fix than repeated intakes.

What the design does support well: exact deterministic scores, a fabrication
count, the degradation curve across patient difficulty, and — with repetitions —
paired interval estimates for every comparison.

---

## Layout

```
evaluation/
├── run_all.py                 ← the single entry point
├── cira_scenarios.json        ← ground-truth scenarios
├── harness/
│   ├── config.py              ← paths, naming, settings, .env
│   ├── common.py              ← deterministic helpers
│   ├── personas.py            ← 3 personas + seeded assignment
│   ├── patient_simulator.py   ← simulated patient
│   ├── structured_score.py    ← PHQ-9 / GAD-7 / safety-flag scoring
│   ├── safety_score.py        ← safety confusion matrix, balanced accuracy
│   ├── record_check.py        ← field enumeration + auto-resolution
│   ├── llm_judge.py           ← record-fidelity + flow judges, blinded
│   ├── provenance.py          ← run manifest, run_id, freshness
│   ├── rule_based_cira.py     ← finite-state baseline engine
│   ├── naive_llm.py           ← prompt-only ablation engine
│   └── stages/
│       ├── run_cira.py            ├── run_rule_based.py
│       ├── run_naive.py           ├── score_records.py
│       └── run_judge.py
├── tools/
│   ├── rescore_contested.py   ← re-aggregate contested over the shared set
│   └── show_intervals.py      ← re-print CIs and paired differences
├── tests/                     ← offline, no API keys
│   ├── test_scoring.py            └── test_personas.py
└── outputs/
    ├── <system>/{transcripts,records}/case_04_01.json
    ├── judge/<system>/case_04_01.json
    └── reports/
        ├── <system>_deterministic.json
        ├── judge_comparison.json
        ├── run_manifest.json
        ├── persona_assignment.json
        └── summary.json           ← includes uncertainty + pairwise_differences
```

Every per-case file is `case_<id>.json`; the folder names its type and system.
Case-id helpers live once in `harness/config.py`: `safe_case_id("04-01")` →
`"04_01"`, `short_case_id("04-01")` → `"01"`.

---

## Running

```bash
python run_all.py                      # full pipeline (~2 hours)
python run_all.py --case 04-01         # one scenario end-to-end
python run_all.py --only score judge summary
python run_all.py --skip cira
python run_all.py --systems rule_based

python run_all.py --repetitions 20     # repeated interactions -> usable CIs

python -m tools.rescore_contested      # shared contested set, no API calls
python -m tools.show_intervals         # re-print CIs, no API calls
```

Individual stages:

```bash
python -m harness.stages.run_cira --case 04-01
python -m harness.stages.score_records --system cira
python -m harness.stages.run_judge --system cira
```

Offline tests, no keys:

```bash
python -m tests.test_scoring     # 73 checks
python -m tests.test_personas    # 55 checks
```

A clean run starts from an empty `outputs/`:

```bash
rm -rf outputs records
python run_all.py 2>&1 | tee full_run.log
grep -c "fell through" full_run.log            # want 0
grep "stalled\|ERROR while running" full_run.log
```

---

## Configuration

Environment variables, read once in `harness/config.py`, loadable from
`evaluation/.env` or `../cira/.env`:

| variable | purpose | default |
|---|---|---|
| `OPEN_ROUTER` | OpenRouter key (patient simulator + judge) | – |
| `OPENROUTER_BASE_URL` | OpenRouter endpoint | `https://openrouter.ai/api/v1` |
| `CIRA_PATIENT_MODEL` | patient simulator model | `openai/gpt-5.4-mini` |
| `CIRA_JUDGE_MODEL` | judge model | `google/gemini-3.1-flash-lite` |
| `CIRA_JUDGE_BASE_URL` / `CIRA_JUDGE_API_KEY` | judge endpoint / key | OpenRouter's |
| `CIRA_JUDGE_REASONING_EFFORT` | thinking level | `minimal` |
| `CIRA_JUDGE_TEMPERATURE` | judge sampling temperature | `0` |
| `CIRA_JUDGE_TIMEOUT` / `CIRA_JUDGE_MAX_RETRIES` | stall protection | `90` / `2` |
| `CIRA_JUDGE_MAX_TOKENS` | judge output cap | `4000` |
| `CIRA_JUDGE_MAX_WORKERS` | concurrent cases judged | `4` |
| `CIRA_MAX_TURNS_PER_SECTION` | per-section turn cap | `30` |
| `CIRA_STALL_LIMIT` | consecutive no-progress turns before a section aborts | `8` |
| `CIRA_NAIVE_MODEL` | ablation model | CIRA's `CIRA_MODEL` |
| `CIRA_NAIVE_MAX_TURNS` | ablation turn cap | `90` |
| `CIRA_PERSONA_SEED` | persona assignment seed | `20260804` |
| `CIRA_PERSONA_STRATEGY` | `balanced` or `random` | `balanced` |
| `CIRA_PERSONA_OVERRIDE` | force one persona onto every case | – |

`CIRA_EVAL_TEMPERATURE` is optional: leave it unset and each persona uses its
own temperature; set it and that value is pinned for every persona, isolating
the prompt's effect from sampling.

---

## Artifact formats

* **Records** (`outputs/<system>/records/case_XX.json`) mirror the scenario
  `patient_facts` layout — twelve sections as nested dicts — plus `case_id`,
  `scenario_case_id`, `safety_flag`, `sections_completed`, `intake_complete`,
  `persona_id` and `run_id`. Runtime state is never written.
* **Transcripts** (`outputs/<system>/transcripts/case_XX.json`) contain only
  real dialogue under `conversation`, plus `patient_behaviour` recording what
  the persona actually did — deferral and hedge counts by section.

Records are checkpointed after every section and again in a `finally` block, so
an interrupted or crashed case still leaves scoreable artifacts.
`intake_complete` distinguishes a partial record from a clean one.

---

## Before publishing

Plan a small human-agreement check on the record verdicts — two or three
hand-labelled cases gives you a number for the "you used an LLM judge" question
at review. The categorical verdicts make that a four-label confusion matrix
rather than a correlation between two floats.