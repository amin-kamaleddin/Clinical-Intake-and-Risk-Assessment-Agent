# CIRA — Clinical Intake and Risk Assessment

A LangGraph-based conversational agent that collects a structured psychiatric
intake record before a patient's appointment, and flags current safety risk
while doing it.

Built for the Interventional Psychiatry Program, Unity Health Toronto
(St. Michael's Hospital).

> This README is written from the code. Where an earlier version of it
> disagreed with the implementation — the entry point, the package name, the
> environment-variable prefix, the default model, how records are saved,
> language support — the code is authoritative and this document has been
> corrected to match.

---

## Running it

```bash
pip install -r requirements.txt
python cira/main.py
```

`main.py` loads `.env`, imports the Gradio app from `ui/app.py`, and launches
it. There is no CLI intake; the agent is driven through the web UI.

`.env` lives at the **project root** (the folder containing `cira/`), not
inside `cira/`. `core/config.py` loads it before reading any environment
variable — if you move that `load_dotenv` call, every setting below silently
falls back to its default.

---

## Configuration

All variables use the `CIRA_` prefix.

| variable | purpose | default |
|---|---|---|
| `CIRA_MODEL` | the intake model | `gpt-5.6-luna` |
| `CIRA_STT_MODEL` | speech to text | `gpt-4o-transcribe` |
| `CIRA_TTS_MODEL` | text to speech | `gpt-4o-mini-tts` |
| `CIRA_TTS_VOICE` | TTS voice | `shimmer` |
| `OPENAI_API_KEY` | provider credential | — |

Never commit `.env`. If it has been committed, rotate the keys.

---

## Project layout

```
cira/
├── main.py                    ← entry point: loads .env, launches the Gradio app
├── core/
│   ├── config.py              ← model names, .env loading (must run before getenv)
│   ├── state.py               ← AliceState, REQUIRED_FIELDS, FIELD_TO_SECTION
│   ├── tools.py               ← save_answer, raise_safety_flag, confirm_no_more_entries
│   ├── validators.py          ← per-field validation and normalisation
│   ├── safety.py              ← deterministic safety gate + crisis message
│   ├── scoring.py             ← PHQ-9 / GAD-7 totals
│   ├── storage.py             ← writes records/<session_id>.json
│   └── audio.py               ← STT / TTS helpers
├── graph/
│   ├── builder.py             ← single-node StateGraph
│   └── nodes.py               ← section_node: the whole intake turn
├── prompts/
│   ├── builder.py             ← assembles the system prompt per turn
│   ├── static_prompt.py       ← role, conversation rules, safety protocol
│   └── section_prompts.py     ← per-section collection instructions
└── tests/
    └── test_safety_gate.py    ← safety regression tests (offline, no keys)
```

The package is `cira/`. Any reference to `alice/` is historical; the state
TypedDict is still named `AliceState` for compatibility.

---

## The intake

Twelve sections, seventy fields, collected one question at a time:

| section | fields |
|---|---|
| general_information | 11 |
| current_concerns | 2 |
| past_psychiatric_history | 9 |
| medications | 4 |
| medical_history | 6 |
| medication_allergies | 2 |
| family_psychiatric_history | 2 |
| substance_use | 8 |
| education_employment_legal_history | 4 |
| personal_history | 4 |
| phq9 | 10 |
| gad7 | 8 |

### Repeatable fields

Eleven fields hold more than one entry — medications, diagnoses, therapies,
medical conditions, family members, jobs. These are **not** complete when they
hold a value. They stay open until the model calls
`confirm_no_more_entries(field_name)`, because otherwise the first saved entry
closes the field and everything the patient says afterwards is lost.

Three things bound this so a field cannot loop:

- an entry answered with a negation (`"None reported."`) closes itself
- saving a later field in the same section implicitly confirms earlier ones
- after `MAX_REPEATABLE_FOLLOWUPS = 5` **consecutive unproductive** turns the
  field auto-confirms. The counter resets whenever the field actually gains
  content, so an interview making progress is never cut off.

### Field routing

`save_answer` writes to the section that **owns** the field, via
`FIELD_TO_SECTION` — not to whichever section happens to be active. A patient
volunteering a medical condition during the concerns section has it filed
correctly. Unknown field names are rejected rather than silently creating a key.

---

## Safety

Three independent paths raise the flag. Two are deterministic; only the third
depends on model judgement.

**1. The deterministic gate** (`core/safety.py`). Regex over the patient's
message, evaluated **clause by clause**. Each clause is checked against the
exclusions (historical, third-person, negated, hypothetical) and then against
the current-first-person risk patterns. Any unexcluded clause stating current
risk fires the gate.

Clause-level matters: applying exclusions to the whole message meant
*"My brother died by suicide and I currently want to die"* was suppressed by the
family-history exclusion, which is a false negative on a live disclosure.

**2. PHQ-9 item 9.** Any saved score above zero raises the flag in code,
regardless of what the conversation contained.

**3. `raise_safety_flag`.** For everything the regex is deliberately too narrow
to catch.

### What the gate will not do

It does not fire on a safety-related word alone. Third-person disclosures
(*"my uncle died by suicide"*), clear denials, and resolved historical events
are excluded by design — false alarms cost clinician trust and, at volume,
cause alarm fatigue.

### After the flag is raised

The crisis message is delivered **once**. A resume directive then enters the
system prompt telling the agent that safety has been handled and its next
message must be the pending intake question. Without it the conversation fills
with safety text and the model keeps generating more, abandoning the intake.

If a self-harm history is disclosed and clarified as historical with no current
risk, `safety_history_cleared` records that. A later re-mention of the same
history does not re-trigger the flag — but the directive states explicitly that
a prior historical assessment **never** suppresses a new current disclosure.

### Guards on the questionnaires

A PHQ-9 or GAD-7 score can only be saved when the patient's message actually
contains a scale selection — a digit 0–3 or one of the four frequency phrases.
Without this, an agent that gave up on a deflected item could record `0`, which
reads as "Not at all": a clinical finding, not a placeholder.

### Tests

```bash
cd cira
python -m tests.test_safety_gate
```

Offline, no keys. Pins 23 statements that **must** trigger and 19 that must
not. A false negative here is the worst outcome the system can produce, so both
directions are asserted.

---

## Records

`core/storage.py` writes `records/<session_id>.json` **after every turn**, not
once at completion. `session_id` is generated once per session, so the filename
is stable and never renamed. It is not derived from patient name or date of
birth.

The directory is created relative to the working directory you launched from.

---

## Language

`SUPPORTED_TEST_LANGUAGES = ["English", "French", "Hindi"]` and the system
prompt instructs the model to reply in `preferred_language`.

**There is currently no automatic language detection.** Nothing sets
`preferred_language`, so in practice every intake runs in English, and the
deterministic crisis message in `core/safety.py` is English-only. Treat
multilingual support as unimplemented rather than partial — a crisis message
that does not reach the patient in their language is a safety issue, not a
localisation gap.

---

## Evaluation

The benchmark lives in the sibling `evaluation/` folder and runs CIRA against a
deterministic rule-based intake and a prompt-only LLM ablation across twelve
simulated patients. See `evaluation/README.md`.

---

## Known limitations

- No automatic language detection (above).
- Switching sections in the UI clears the model conversation. Because the
  prompt withholds partial multi-detail entries, switching mid-entry can
  discard information that was collected but not yet saved.
- UI-only state fields are not declared in `AliceState`. Anything not declared
  there is dropped by LangGraph on every `graph.invoke()` — if you add state,
  declare it in the TypedDict, not only in `initial_state`.
- Voice input shows only a placeholder, not the transcript, so a patient cannot
  verify a mis-transcription before it enters the record.
- Successful TTS temporary files are not cleaned up.