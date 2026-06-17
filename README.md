# ALICE — Clinical Intake Assistant

ALICE is an AI-powered conversational agent that conducts structured clinical intake interviews before a patient's appointment. Built with LangGraph and GPT-5.4-mini, it collects patient information through natural conversation, validates responses in real time, and flags safety concerns automatically.

---

## Features

- **Guided intake flow** — collects General Information and Current Concerns one question at a time
- **Real-time validation** — formats and validates dates, postal codes, phone numbers, emails, and addresses as they are entered
- **Safety protocol** — detects distress signals, probes appropriately, and raises a flag with a hardcoded crisis response when needed
- **Persistent records** — saves completed intake records as JSON files to a local `records/` folder
- **Live info panel** — displays collected fields with a progress bar as the conversation progresses

---

## Project Structure

```
alice/
├── main.py                        # Entry point
├── core/
│   ├── state.py                   # TypedDicts, REQUIRED_FIELDS, initial_state
│   ├── tools.py                   # LangChain tools (save_answer, raise_safety_flag)
│   ├── validators.py              # Field validators and registry
│   └── storage.py                 # JSON record persistence
├── prompts/
│   ├── static_prompt.py           # Core system prompt and safety protocol
│   ├── section_prompts.py         # Per-section field collection instructions
│   └── builder.py                 # Runtime prompt assembly from state
├── graph/
│   ├── nodes.py                   # section_node (turn execution logic)
│   └── builder.py                 # LangGraph compilation
└── ui/
    ├── styles.py                  # CSS and avatars
    ├── display.py                 # Info panel renderer
    ├── handlers.py                # Gradio event callbacks
    └── app.py                     # Gradio Blocks layout
```

---

## Setup

**1. Clone the repository and install dependencies**

```bash
pip install langchain langchain-openai langgraph gradio python-dotenv pillow
```

**2. Create a `.env` file in the project root**

```
OPENAI_API_KEY=your_openai_api_key_here
```

**3. Run the app**

```bash
cd alice
python main.py
```

The Gradio interface will open in your browser. Click a section button to begin the intake.

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

When a patient expresses distress, ALICE pauses intake, probes once, and raises a flag if the response is anything other than a clear denial. The crisis response is hardcoded — the LLM never generates it. After flagging, intake resumes normally on the next turn.

---

*Built at Unity Health Toronto — St. Michael's Hospital*