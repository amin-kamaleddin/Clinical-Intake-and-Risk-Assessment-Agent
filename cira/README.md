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
python cira/main.py          # http://127.0.0.1:8000
```

`main.py` starts the FastAPI service in `web/server.py`, which serves the
interface from `web/static/` and exposes the agent behind a small JSON API.
There is no CLI intake; the agent is driven through the web interface.

Records are written relative to the directory you start from, so start the
server where those records should land (see **Records** below).

| variable | purpose | default |
|---|---|---|
| `CIRA_HOST` | address to bind | `127.0.0.1` |
| `CIRA_PORT` | port | `8000` |

Bind to `0.0.0.0` only behind something that terminates TLS and authenticates
the user. The service has no login of its own, and every record it holds is
identifying clinical information.

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
├── main.py                    ← entry point: launches the web service
├── core/
│   ├── languages.py           ← the six supported languages, in one place
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
├── ui/
│   └── schema.py              ← sections, field labels, state normalisation
├── web/
│   ├── server.py              ← FastAPI: the JSON API and the static files
│   └── static/                ← the interface (index.html, app.css, app.js)
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

`core/languages.py` is the single source of truth, shared by the agent and the
evaluation harness. Six languages are supported: English, French, Mandarin
Chinese, Arabic, Hindi, Farsi. Each entry carries the crisis message, the
PHQ-9 / GAD-7 frequency and difficulty phrases, the question marks the scorer
accepts, the ISO code for transcription, and the voice instructions for speech.

The patient chooses the language in the interface, and may change it
mid-intake. Two things hold regardless:

- **The record is always written in English.** The conversation is not. This is
  what keeps one intake from being split across two languages, and it is what
  the evaluation measures against English ground truth.
- **The crisis message is delivered in the patient's language**, from the
  translation in `languages.py`, falling back to the English wording in
  `core/safety.py` only if a language has none. Saying nothing to a patient at
  risk is worse than saying it in the wrong language.

Speech works in all six: the reply is spoken with per-language voice
instructions, and a spoken answer is transcribed **with** the chosen language
rather than by detection — a one-word answer gives a detector almost nothing,
and a wrong guess returns fluent nonsense rather than an error.

There is still no automatic detection: the language is chosen, never inferred.

---

## Deploying it

One service, one port, no build step - the interface is plain HTML, CSS and
JavaScript served by the same process as the API.

```bash
pip install -r cira/requirements.txt
CIRA_HOST=0.0.0.0 CIRA_PORT=8000 python cira/main.py
```

Before it faces anyone real:

- put it behind TLS and authentication; it has neither
- point the working directory at access-controlled storage, not the checkout
- keep `.env` out of the image and out of the repository
- confirm that storing this data in that location is permitted under PHIPA and
  your institution's privacy rules. The record holds a name, a date of birth, a
  home address, a phone number, an email address, psychiatric history and
  suicidality. Hosting is the easy part of that sentence.

---

## Evaluation

The benchmark lives in the sibling `evaluation/` folder and runs CIRA against a
deterministic rule-based intake and a prompt-only LLM ablation across twelve
simulated patients. See `evaluation/README.md`.

---

## Known limitations

- The language is chosen, never detected (above).
- Switching sections clears the model conversation. Because the
  prompt withholds partial multi-detail entries, switching mid-entry can
  discard information that was collected but not yet saved.
- Interface-only state fields are not declared in `AliceState`. Anything not declared
  there is dropped by LangGraph on every `graph.invoke()` — if you add state,
  declare it in the TypedDict, not only in `initial_state`.
- A transcript enters the record on the same turn it is shown, so a patient
  sees a mis-transcription only after it has been saved.
- Successful TTS temporary files are not cleaned up.
- Sessions are held in memory, so a restart ends every intake in progress. The
  records already written survive; the conversations do not.
- The service has no authentication of its own.