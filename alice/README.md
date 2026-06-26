# Triage_Agent — Clinical Intake Assistant

Triage_Agent is an AI-powered conversational agent that conducts structured clinical intake interviews before a patient's appointment. Built with LangGraph and GPT-5.4-mini, the assistant (ALICE) collects patient information across twelve intake sections through natural multilingual conversation, validates responses in real time, supports two-way voice interaction, computes PHQ-9 and GAD-7 scores, and flags safety concerns through both a deterministic keyword gate and an LLM safety protocol.

---

## Features

- **Twelve intake sections** — General Information, Current Concerns, Past Psychiatric History, Medications, Medical History, Medication Allergies, Family Psychiatric History, Substance Use, Education/Employment/Legal History, Personal History, PHQ-9, and GAD-7
- **Real-time validation** — dates, postal codes, phone numbers, emails, addresses, height/weight, and PHQ-9/GAD-7 response options
- **Multilingual** — detects and replies in English, French, or Hindi, while storing records in English
- **Two-way voice** — optional text-to-speech for ALICE's replies and speech-to-text for patient answers
- **Layered safety** — a deterministic trilingual keyword gate runs before the LLM, backed by a full LLM safety protocol that distinguishes current vs. historical concerns
- **Automated scoring** — PHQ-9 and GAD-7 totals computed as questionnaire items are answered
- **Persistent records** — saves the complete record as JSON once all sections are finished
- **Live info panel** — per-section progress bar and collected fields, with score badges

---

## Project Structure

```
alice/
├── main.py                        # Entry point
├── requirements.txt
├── core/
│   ├── config.py                  # Model names and settings (env-overridable)
│   ├── state.py                   # All section schemas, REQUIRED_SECTIONS, initial_state
│   ├── tools.py                   # LangChain tools (save_answer, raise_safety_flag)
│   ├── validators.py              # Field validators and registry
│   ├── safety.py                  # Deterministic trilingual safety gate + crisis reply
│   ├── scoring.py                 # PHQ-9 / GAD-7 total calculation
│   ├── storage.py                 # Full-record JSON persistence
│   └── audio.py                   # OpenAI text-to-speech and speech-to-text
├── prompts/
│   ├── static_prompt.py           # Persona, language rules, global safety protocol
│   ├── section_prompts.py         # Per-section field collection instructions
│   └── builder.py                 # Pending-field logic + runtime prompt assembly
├── graph/
│   ├── nodes.py                   # section_node + safety/tool/completion helpers
│   └── builder.py                 # LangGraph compilation
└── ui/
    ├── schema.py                  # UI section defaults, labels, state normalization
    ├── styles.py                  # CSS and avatars
    ├── display.py                 # Info panel renderer
    ├── voice.py                   # ALICE / patient voice toggle handlers
    ├── handlers.py                # Gradio event callbacks
    └── app.py                     # Gradio Blocks layout
```

---

## Configuration

Model names and settings live in `core/config.py` and can be overridden with environment variables for reproducible runs:

```
ALICE_MODEL        (default: gpt-5.4-mini)
ALICE_STT_MODEL    (default: gpt-4o-transcribe)
ALICE_TTS_MODEL    (default: gpt-4o-mini-tts)
ALICE_TTS_VOICE    (default: shimmer)
```

---

## Setup

**1. Create a virtual environment and install dependencies**

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**2. Create a `.env` file in the project root**

```
OPENAI_API_KEY=your_openai_api_key_here
```

**3. Run the app**

```bash
python main.py
```

Click a section button to begin the intake.

---

## Safety

Safety detection runs in two layers. A deterministic keyword gate (`core/safety.py`) checks each patient message for explicit crisis phrases in English, French, and Hindi before the LLM is ever called; a match short-circuits to a hardcoded crisis response. Beyond that, the LLM follows a global safety protocol that separates clear current danger (flag immediately), possible-but-unclear concerns (one clarification, then flag if unconfirmed), and ordinary distress or historical concerns (continue intake). The crisis response text is hardcoded — the LLM never generates it.

---

## Records

Completed records are saved to `records/` once every section is finished, named `{patient_name}_{date_of_birth}.json`. Re-saving the same patient overwrites the existing file.

---

*Built at Unity Health Toronto — St. Michael's Hospital*
