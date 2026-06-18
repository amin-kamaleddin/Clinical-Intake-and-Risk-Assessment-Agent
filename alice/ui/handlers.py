import copy

import gradio as gr

from core.state import AliceState, initial_state
from core.audio import text_to_speech, transcribe_audio
from graph.builder import graph
from ui.display import format_display


def get_fresh_state() -> AliceState:
    """Return a deep copy of initial_state, ensuring voice fields exist."""
    state = copy.deepcopy(initial_state)
    state.setdefault("latest_input_source", "typed text")
    state.setdefault("speech_to_text_active", False)
    return state


def start():
    """
    Initialize the UI on page load. ALICE voice starts enabled.
    Returns: (history, state, info_panel, welcome_audio)
    """
    state        = get_fresh_state()
    welcome_text = "Welcome! Please select a section above to begin your intake."
    history      = [{"role": "assistant", "content": f"👋 {welcome_text}"}]

    # A browser may block this first autoplay until the first interaction.
    welcome_audio = text_to_speech(welcome_text)

    return history, state, format_display(state), welcome_audio


def run_patient_message(
    message,
    displayed_user_message,
    history,
    alice_state,
    alice_voice_enabled,
    input_source,
    speech_to_text_active,
):
    """Shared core for typed and spoken patient messages."""
    if alice_state is None:
        alice_state = get_fresh_state()

    history = history or []

    if alice_state.get("current_section") is None or not message or not message.strip():
        return history, alice_state, format_display(alice_state), None

    alice_state["latest_input_source"]   = input_source
    alice_state["speech_to_text_active"] = speech_to_text_active

    alice_state["messages"] = alice_state.get("messages", []) + [
        {"role": "user", "content": message.strip()}
    ]

    alice_state = graph.invoke(alice_state)
    reply = alice_state["messages"][-1]["content"]

    updated_history = history + [
        {"role": "user",      "content": displayed_user_message},
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
    """
    Transcribe a recording privately and submit it immediately.
    The UI shows only a voice-response marker, not the raw transcript.
    Returns: (history, state, info_panel, reply_audio, recorder_reset, status)
    """
    if alice_state is None:
        alice_state = get_fresh_state()

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

    history, alice_state, display, reply_audio = run_patient_message(
        message=transcript,
        displayed_user_message="🎤 Voice response",
        history=history,
        alice_state=alice_state,
        alice_voice_enabled=alice_voice_enabled,
        input_source="speech-to-text",
        speech_to_text_active=True,
    )

    return (
        history, alice_state, display,
        reply_audio, gr.update(value=None), "Voice response sent automatically.",
    )


def switch_section(section, alice_state, alice_voice_enabled, patient_voice_enabled):
    """Open an intake section and ask its first pending question."""
    if alice_state is None:
        alice_state = get_fresh_state()

    alice_state["current_section"]       = section
    alice_state["messages"]              = []
    alice_state["latest_input_source"]   = "typed text"
    alice_state["speech_to_text_active"] = patient_voice_enabled

    alice_state = graph.invoke(alice_state)
    reply = alice_state["messages"][-1]["content"]

    history     = [{"role": "assistant", "content": reply}]
    reply_audio = text_to_speech(reply) if alice_voice_enabled else None

    return history, alice_state, format_display(alice_state), reply_audio
