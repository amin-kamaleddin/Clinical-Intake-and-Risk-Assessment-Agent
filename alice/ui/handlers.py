import copy
import uuid

import gradio as gr

from core.state import initial_state
from core.audio import text_to_speech, transcribe_audio
from graph.builder import graph
from ui.schema import normalize_state_schema
from ui.display import format_display


def get_fresh_state():
    state = copy.deepcopy(initial_state)
    state["session_id"] = uuid.uuid4().hex[:8]
    return normalize_state_schema(state)


def start():
    """Initialize the UI. ALICE voice starts enabled."""
    state = get_fresh_state()
    welcome_text = "Welcome! Please select a section above to begin your intake."
    welcome_history = [{"role": "assistant", "content": f"👋 {welcome_text}"}]
    welcome_audio = text_to_speech(welcome_text)
    return welcome_history, state, format_display(state), welcome_audio


def run_patient_message(
    message,
    displayed_user_message,
    history,
    alice_state,
    alice_voice_enabled,
    input_source,
    speech_to_text_active,
):
    """Shared logic for typed and spoken patient messages."""
    alice_state = normalize_state_schema(alice_state)
    history = history or []

    if alice_state.get("current_section") is None or not message or not message.strip():
        return history, alice_state, format_display(alice_state), None

    alice_state["latest_input_source"] = input_source
    alice_state["speech_to_text_active"] = speech_to_text_active

    alice_state["messages"] = alice_state.get("messages", []) + [
        {"role": "user", "content": message.strip()}
    ]

    alice_state = graph.invoke(alice_state)
    alice_state = normalize_state_schema(alice_state)
    reply = alice_state["messages"][-1]["content"]

    updated_history = history + [
        {"role": "user", "content": displayed_user_message},
        {"role": "assistant", "content": reply},
    ]

    reply_audio = text_to_speech(reply) if alice_voice_enabled else None

    return updated_history, alice_state, format_display(alice_state), reply_audio


def chat(message, history, alice_state, alice_voice_enabled, patient_voice_enabled):
    """Submit a typed patient message to the graph."""
    clean_message = message.strip() if message else ""
    return run_patient_message(
        message=clean_message,
        displayed_user_message=clean_message,
        history=history,
        alice_state=alice_state,
        alice_voice_enabled=alice_voice_enabled,
        input_source="typed text",
        speech_to_text_active=patient_voice_enabled,
    )


def voice_chat(audio_file, history, alice_state, alice_voice_enabled, patient_voice_enabled):
    """Transcribe a recording and submit it immediately."""
    alice_state = normalize_state_schema(alice_state)
    history = history or []

    if not patient_voice_enabled:
        return (
            history, alice_state, format_display(alice_state),
            None, gr.update(value=None), "Patient Voice is off.",
        )

    if alice_state.get("current_section") is None:
        return (
            history, alice_state, format_display(alice_state),
            None, gr.update(value=None),
            "Please select an intake section before recording.",
        )

    transcript = transcribe_audio(audio_file)
    if not transcript:
        return (
            history, alice_state, format_display(alice_state),
            None, gr.update(value=None),
            "I could not understand the recording. Please try again.",
        )

    updated_history, updated_state, updated_display, reply_audio = run_patient_message(
        message=transcript,
        displayed_user_message="🎤 Voice response",
        history=history,
        alice_state=alice_state,
        alice_voice_enabled=alice_voice_enabled,
        input_source="speech-to-text",
        speech_to_text_active=True,
    )

    return (
        updated_history, updated_state, updated_display,
        reply_audio, gr.update(value=None), "Voice response sent automatically.",
    )


def switch_section(section, alice_state, alice_voice_enabled, patient_voice_enabled):
    """Open an intake section and ask its first pending question."""
    alice_state = normalize_state_schema(alice_state)

    alice_state["current_section"] = section
    alice_state["messages"] = []
    alice_state["latest_input_source"] = "typed text"
    alice_state["speech_to_text_active"] = patient_voice_enabled

    alice_state = graph.invoke(alice_state)
    alice_state = normalize_state_schema(alice_state)
    reply = alice_state["messages"][-1]["content"]

    section_history = [{"role": "assistant", "content": reply}]
    reply_audio = text_to_speech(reply) if alice_voice_enabled else None

    return section_history, alice_state, format_display(alice_state), reply_audio


def make_switch_handler(section_name):
    """Create a Gradio callback bound to one section."""
    def handler(state, alice_voice, patient_voice):
        return switch_section(section_name, state, alice_voice, patient_voice)
    return handler
