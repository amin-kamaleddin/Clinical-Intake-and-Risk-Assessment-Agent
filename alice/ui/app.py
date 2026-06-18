import gradio as gr

from ui.styles import CUSTOM_CSS, ALICE_AVATAR, USER_AVATAR
from ui.display import format_display
from ui.handlers import start, chat, voice_chat, switch_section
from ui.voice import toggle_alice_voice, toggle_patient_voice


def build_demo() -> gr.Blocks:
    with gr.Blocks(title="ALICE", css=CUSTOM_CSS, theme=gr.themes.Soft()) as demo:

        alice_state = gr.State(None)

        # ALICE text-to-speech is ON by default.
        alice_voice_enabled = gr.State(True)
        # Patient speech-to-text is OFF by default.
        patient_voice_enabled = gr.State(False)

        # ── Header ─────────────────────────────────────────────────────────────
        gr.HTML("""
            <div class="alice-header">
                <div style="
                    width:52px; height:52px; border-radius:50%;
                    background:#dbeafe; display:flex; align-items:center;
                    justify-content:center; flex-shrink:0; font-size:26px;">
                    👩‍⚕️
                </div>
                <div>
                    <h1>ALICE</h1>
                    <p>Clinical Intake Assistant</p>
                </div>
            </div>
        """)

        # ── Section buttons ─────────────────────────────────────────────────────
        with gr.Row():
            btn_general  = gr.Button("General Information", elem_classes="btn-general")
            btn_concerns = gr.Button("Current Concerns",    elem_classes="btn-concerns")

        # ── Main layout ──────────────────────────────────────────────────────────
        with gr.Row():
            with gr.Column(scale=2):
                chatbot = gr.Chatbot(
                    height=520,
                    show_label=False,
                    avatar_images=(USER_AVATAR, ALICE_AVATAR),
                )

                msg = gr.Textbox(
                    placeholder="Type your message here...",
                    show_label=False,
                    container=False,
                )

                # ── Voice control cards ──────────────────────────────────────────
                with gr.Row():
                    with gr.Column(elem_classes="voice-card"):
                        gr.HTML("""
                            <div class="voice-title">ALICE Voice</div>
                            <div class="voice-description">
                                Reads ALICE's replies aloud automatically.
                            </div>
                        """)
                        alice_voice_button = gr.Button(
                            "🔊 ALICE Voice: ON",
                            elem_classes="alice-voice-button",
                        )

                    with gr.Column(elem_classes="voice-card"):
                        gr.HTML("""
                            <div class="voice-title">Patient Voice</div>
                            <div class="voice-description">
                                Records and sends the patient's answer automatically.
                            </div>
                        """)
                        patient_voice_button = gr.Button(
                            "🎤 Patient Voice: OFF",
                            elem_classes="patient-voice-button",
                        )

                # Kept rendered for autoplay; controls hidden via CSS.
                alice_audio_output = gr.Audio(
                    autoplay=True,
                    interactive=False,
                    show_label=False,
                    container=False,
                    elem_id="alice-audio-output",
                )

                # Hidden until Patient Voice is enabled.
                patient_audio_input = gr.Audio(
                    sources=["microphone"],
                    type="filepath",
                    label="Record your answer",
                    visible=False,
                    elem_classes="patient-recorder",
                )

                patient_status = gr.Markdown(
                    "Patient Voice is off.",
                    elem_classes="patient-status",
                )

                gr.Markdown(
                    (
                        "ALICE's voice and patient transcription are AI-generated. "
                        "Patient recordings are transcribed and submitted automatically."
                    ),
                    elem_classes="ai-disclosure",
                )

            with gr.Column(scale=1):
                info_display = gr.HTML(
                    value=format_display(None),
                    elem_classes="info-box",
                    label="Collected Information",
                )

        # ── Voice controls ───────────────────────────────────────────────────────
        alice_voice_button.click(
            toggle_alice_voice,
            inputs=[alice_voice_enabled, chatbot],
            outputs=[alice_voice_enabled, alice_voice_button, alice_audio_output],
        )

        patient_voice_button.click(
            toggle_patient_voice,
            inputs=[patient_voice_enabled, alice_state],
            outputs=[
                patient_voice_enabled, alice_state, patient_voice_button,
                patient_audio_input, patient_status,
            ],
        )

        # Stopping the recording transcribes and submits it immediately.
        patient_audio_input.stop_recording(
            voice_chat,
            inputs=[
                patient_audio_input, chatbot, alice_state,
                alice_voice_enabled, patient_voice_enabled,
            ],
            outputs=[
                chatbot, alice_state, info_display,
                alice_audio_output, patient_audio_input, patient_status,
            ],
        )

        # ── Chat events ──────────────────────────────────────────────────────────
        msg.submit(
            chat,
            inputs=[msg, chatbot, alice_state, alice_voice_enabled, patient_voice_enabled],
            outputs=[chatbot, alice_state, info_display, alice_audio_output],
        ).then(lambda: "", outputs=msg)

        btn_general.click(
            lambda state, av, pv: switch_section("general_information", state, av, pv),
            inputs=[alice_state, alice_voice_enabled, patient_voice_enabled],
            outputs=[chatbot, alice_state, info_display, alice_audio_output],
        )

        btn_concerns.click(
            lambda state, av, pv: switch_section("current_concerns", state, av, pv),
            inputs=[alice_state, alice_voice_enabled, patient_voice_enabled],
            outputs=[chatbot, alice_state, info_display, alice_audio_output],
        )

        demo.load(
            start,
            inputs=[],
            outputs=[chatbot, alice_state, info_display, alice_audio_output],
        )

    return demo


demo = build_demo()
