# Triage-Agent — CIRA and its evaluation benchmark

Two things live here:

- **`cira/`** — CIRA (Clinical Intake and Risk Assessment), a LangGraph
  conversational agent that collects a structured psychiatric intake record
  before a patient's appointment and flags current safety risk while doing it.
- **`evaluation/`** — a benchmark that runs CIRA against two baselines over
  twelve simulated patients and scores all three on the same measures.

Built for the Interventional Psychiatry Program, Unity Health Toronto
(St. Michael's Hospital).

```
Triage-Agent/
├── cira/                ← the agent            → cira/README.md
├── evaluation/          ← the benchmark        → evaluation/README.md
└── .env                 ← API keys (never commit this)
```

---

## Quick start

```bash
# the agent
pip install -r cira/requirements.txt
python cira/main.py

# the benchmark
pip install -r evaluation/requirements.txt
cd evaluation && python run_all.py                  # single run
cd evaluation && python run_all.py --repetitions 20 # repeated -> confidence intervals
```

`.env` belongs at the project root, not inside `cira/`. If it has ever been
committed, rotate the keys.

---

## What CIRA does

Twelve sections, seventy fields, one question at a time, with per-field
validation and normalisation. Repeatable fields (medications, diagnoses, family
history, jobs) stay open until the patient confirms there are no further
entries, so the first saved entry does not close the field.

Safety has three independent paths to the flag. Two are deterministic — a
clause-level regex gate over the patient's message, and any PHQ-9 item 9 score
above zero — and the third is a tool the model can call for everything the regex
is deliberately too narrow to catch. A questionnaire score cannot be recorded at
all unless the patient's message actually contains a scale selection, so an
unanswered item can never be silently written as `0`.

Details in **`cira/README.md`**.

---

## What the benchmark measures

Twelve scenarios, five of which involve genuine current risk, plus two built
specifically to *look* like risk without being it — a relative who died by
suicide, and historical non-suicidal self-injury.

Three systems:

| system | what it is |
|---|---|
| `cira` | the live agent |
| `rule_based` | a deterministic finite-state intake, no LLM anywhere |
| `naive_llm` | a prompt-only LLM architecture ablation — one intake prompt plus a structured-extraction call |

Each scenario is run against one of three **patient personas** — `clear`,
`moderate`, `confused` — assigned from a seed so every system faces the same
patient on the same case. The persona changes how the patient communicates,
never what they know: a confused patient rambles, misreads questions and needs
the frequency scale re-explained, but every concrete fact it eventually states
matches ground truth exactly.

Four metrics, split by whether an exact answer exists:

| metric | source | measures |
|---|---|---|
| `safety_score` | **code** | flag sensitivity and specificity, balanced accuracy |
| `structured_score` | **code** | PHQ-9 and GAD-7 items and totals |
| `record_score` | LLM verdicts, aggregated in code | free-text capture, paraphrase-tolerant |
| `flow_score` | LLM, holistic | interviewing quality |

Plus a fabrication count — fields written with no ground truth behind them.

### Repetitions and confidence intervals

A single interaction per scenario is one realisation of a stochastic process, so
a difference like 0.9308 vs 0.9285 cannot be told apart from sampling noise.
`--repetitions N` runs each scenario independently N times, with the same
patient seed across all three systems at a given repetition, so comparisons stay
paired.

Every metric is then reported as an estimate with a **95% confidence interval**,
and every system pair gets a **paired difference** with a significance marker:

```
PAIRED DIFFERENCES  (* = 95% CI excludes zero; the claim test)
  cira - naive_llm    fabricated_fields   -0.750 [-1.250, -0.333]  *
  cira - naive_llm    flow_score          -0.117 [-0.185, -0.056]  *
  cira - rule_based   record_score        +0.024 [-0.017, +0.068]  (n.s.)
```

`*` is the only basis for claiming one system beats another. Overlapping
individual intervals do **not** mean a difference is zero — read the paired row.

Details, including why each metric is defined the way it is, in
**`evaluation/README.md`**.

---

## Reading results honestly

A few things are worth stating up front, because they bound what the numbers
can support.

**Run repetitions before comparing.** With `--repetitions 1` there are no usable
intervals and no difference is claimable. With repetitions, use the paired row
and its `*` marker rather than the point estimates.

**Twelve scenarios is a small sample, and repetitions do not fix that.**
Repetitions reduce sampling variance, not scenario coverage. Safety specificity
still moves in steps of 1/7 ≈ 0.14 — one false alarm is the whole gap between
0.857 and 1.0 no matter how many times you run it.

**The strong results are the large ones.** The fabrication rate and the
degradation curve across patient difficulty separate the systems by margins that
survive the noise. Small leads on record and flow generally do not.

**`flow_score` is the noisiest metric.** The same system on the same scenario has
varied by ~0.15 between repetitions. Check `flow_variability` before quoting a
flow comparison.

**Provenance is recorded, so use it.** Every run writes
`outputs/reports/run_manifest.json` with the run id, git revision, every model
name, the persona seed, and hashes of the scenario file and every prompt file.
Artifacts carry their `run_id`, and scoring warns when a report mixes runs.
Before quoting a number, check it came from one build.

**The judge is blinded, and that required more than removing a field name.**
System names are stripped from the payload, speaker labels are rewritten, and
system names are redacted from message text — CIRA introduces itself by name in
its opening line, which by itself defeated the blinding.

---

## Tests

All offline. No API keys, no network.

```bash
cd cira        && python -m tests.test_safety_gate    # 46 checks
cd evaluation  && python -m tests.test_scoring        # 73 checks
cd evaluation  && python -m tests.test_personas       # 55 checks
```

Re-print the intervals from saved reports without re-running anything:

```bash
cd evaluation && python -m tools.show_intervals
```

The safety gate tests pin both error directions: statements that **must**
trigger the flag, and statements that must not. A false negative there is the
worst outcome this system can produce, so it is asserted rather than assumed.

---

## Known limitations

- **No automatic language detection.** Three languages are declared and the
  prompt honours `preferred_language`, but nothing sets it, so every intake runs
  in English and the deterministic crisis message is English-only. Treat
  multilingual support as unimplemented rather than partial.
- **No resume for interrupted runs.** Artifacts survive a crash, but re-running
  restarts from the beginning and overwrites. Back up `outputs/` between batches
  for long repeated runs.
- **One judge model, one judge pass.** Sensitivity to the choice of judge is not
  measured.
- **UI gaps**: switching sections clears the model conversation and can discard
  a partially collected entry; voice input shows a placeholder rather than the
  transcript, so a patient cannot check a mis-transcription before it enters the
  record; TTS temporary files are not cleaned up.
- **State schema drift**: UI-only fields are not declared in `AliceState`.
  Anything not declared there is dropped by LangGraph on every `graph.invoke()`.
  If you add state, declare it in the TypedDict — not only in `initial_state`.

---

## If you are picking this up

Read `evaluation/README.md` first. It explains why each metric is defined as it
is, and most of those definitions exist because an earlier, more obvious version
turned out to measure the wrong thing — plain accuracy hiding a total safety
failure behind an unbalanced class split, a per-system contested set that
penalised the system with the most exact matches, a pass/fail gate dominated by
heuristics. The reasoning is written down next to each one.