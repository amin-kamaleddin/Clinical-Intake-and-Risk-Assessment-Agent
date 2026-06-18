# Triage_Agent — Clinical Intake Assistant

Triage_Agent is an AI-powered conversational agent that conducts structured clinical intake interviews before a patient's appointment. Built with LangGraph and GPT-5.4-mini, the assistant (ALICE) collects patient information through natural conversation, validates responses in real time, supports two-way voice interaction, and flags safety concerns automatically.

---

## Features

- **Guided intake flow** — collects General Information and Current Concerns one question at a time
- **Real-time validation** — formats and validates dates, postal codes, phone numbers, emails, and addresses as they are entered
- **Two-way voice** — optional text-to-speech for ALICE's replies (OpenAI TTS) and speech-to-text for patient answers (OpenAI transcription), with spelling confirmation for names in voice mode
- **Safety protocol** — detects distress signals, probes appropriately, and raises a flag with a hardcoded crisis response when needed
- **Persistent records** — saves completed intake records as JSON files to a local `records/` folder
- **Live info panel** — displays collected fields with a progress bar as the conversation progresses

---

## Project Structure

```
triage_agent/
├── main.py                        # Entry point
├── requirements.txt
├── core/
│   ├── state.py                   # TypedDicts, REQUIRED_FIELDS, initial_state
│   ├── tools.py                   # LangChain tools (save_answer, raise_safety_flag)
│   ├── validators.py              # Field validators and registry
│   ├── storage.py                 # JSON record persistence
│   └── audio.py                   # OpenAI text-to-speech and speech-to-text
├── prompts/
│   ├── static_prompt.py           # Core system prompt, safety protocol, voice rules
│   ├── section_prompts.py         # Per-section field collection instructions
│   └── builder.py                 # Runtime prompt assembly from state
├── graph/
│   ├── nodes.py                   # section_node (turn execution logic)
│   └── builder.py                 # LangGraph compilation
└── ui/
    ├── styles.py                  # CSS and avatars
    ├── display.py                 # Info panel renderer
    ├── voice.py                   # ALICE / patient voice toggle handlers
    ├── handlers.py                # Gradio event callbacks (chat, voice, sections)
    └── app.py                     # Gradio Blocks layout
```

---

## Setup

**1. Clone the repository and install dependencies**

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

The Gradio interface will open in your browser. Click a section button to begin the intake.

---

## Voice

ALICE Voice (text-to-speech) is **on by default** and reads each of the assistant's replies aloud. It can be toggled off with the 🔊 button.

Patient Voice (speech-to-text) is **off by default**. When enabled with the 🎤 button, a microphone recorder appears; stopping a recording transcribes the answer and submits it automatically. In voice mode, the assistant asks patients to spell names letter by letter to avoid transcription errors.

---

## Records

Completed records are saved to `records/` when both sections are finished.
Each file is named `{patient_name}_{date_of_birth}.json` and contains:

```json
{
  "saved_at": "2026-06-13T14:30:22",
  "general_information": { ... },
  "current_concerns": { ... },
  "safety_flag": false
}
```

Re-saving the same patient overwrites the existing file rather than creating a duplicate.

---

## Safety

When a patient expresses distress, the assistant pauses intake, probes once, and raises a flag if the response is anything other than a clear denial. The crisis response is hardcoded — the LLM never generates it. After flagging, intake resumes normally on the next turn.

---

*Built at Unity Health Toronto — St. Michael's Hospital*