import gradio as gr

from core.audio import text_to_speech
from ui.schema import normalize_state_schema


def get_latest_alice_message(history):
    """Return the latest assistant text currently displayed in the chat."""
    for message in reversed(history or []):
        if isinstance(message, dict) and message.get("role") == "assistant":
            content = message.get("content")
            if isinstance(content, str):
                return content
    return None


def toggle_alice_voice(currently_enabled, history):
    """Toggle ALICE text-to-speech."""
    new_state = not currently_enabled

    if new_state:
        latest_message = get_latest_alice_message(history)
        audio_file = text_to_speech(latest_message) if latest_message else None
        return new_state, gr.update(value="🔊 ALICE Voice: ON"), audio_file

    return new_state, gr.update(value="🔇 ALICE Voice: OFF"), None


def toggle_patient_voice(currently_enabled, alice_state):
    """Toggle patient speech-to-text."""
    alice_state = normalize_state_schema(alice_state)
    new_state = not currently_enabled

    alice_state["speech_to_text_active"] = new_state
    alice_state["latest_input_source"] = "typed text"

    if new_state:
        return (
            new_state,
            alice_state,
            gr.update(value="🎤 Patient Voice: ON"),
            gr.update(visible=True, value=None),
            "Patient Voice is on. Record an answer; it will be sent automatically.",
        )

    return (
        new_state,
        alice_state,
        gr.update(value="🎤 Patient Voice: OFF"),
        gr.update(visible=False, value=None),
        "Patient Voice is off.",
    )
