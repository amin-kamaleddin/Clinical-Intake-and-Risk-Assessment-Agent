import gradio as gr

from ui.styles import CUSTOM_CSS, ALICE_AVATAR, USER_AVATAR
from ui.display import format_display
from ui.handlers import start, chat, voice_chat, make_switch_handler
from ui.voice import toggle_alice_voice, toggle_patient_voice


def build_demo() -> gr.Blocks:
    with gr.Blocks(title="ALICE", css=CUSTOM_CSS, theme=gr.themes.Soft()) as demo:

        alice_state = gr.State(None)
        alice_voice_enabled = gr.State(True)
        patient_voice_enabled = gr.State(False)

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

        gr.HTML('<div class="section-nav-label">Intake Sections</div>')

        section_buttons = {}

        with gr.Row(elem_classes="section-nav-row"):
            section_buttons["general_information"] = gr.Button(
                "General Information",
                elem_classes=["section-button", "btn-general"],
            )
            section_buttons["current_concerns"] = gr.Button(
                "Current Concerns",
                elem_classes=["section-button", "btn-concerns"],
            )
            section_buttons["past_psychiatric_history"] = gr.Button(
                "Past Psychiatric History",
                elem_classes=["section-button", "btn-history"],
            )
            section_buttons["medications"] = gr.Button(
                "Medications",
                elem_classes=["section-button", "btn-medications"],
            )

        with gr.Row(elem_classes="section-nav-row"):
            section_buttons["medical_history"] = gr.Button(
                "Medical History",
                elem_classes=["section-button", "btn-medical-history"],
            )
            section_buttons["medication_allergies"] = gr.Button(
                "Medication Allergies",
                elem_classes=["section-button", "btn-allergies"],
            )
            section_buttons["family_psychiatric_history"] = gr.Button(
                "Family Psychiatric History",
                elem_classes=["section-button", "btn-family-history"],
            )
            section_buttons["substance_use"] = gr.Button(
                "Substance Use",
                elem_classes=["section-button", "btn-substance-use"],
            )

        with gr.Row(elem_classes="section-nav-row"):
            section_buttons["education_employment_legal_history"] = gr.Button(
                "Education, Employment & Legal",
                elem_classes=["section-button", "btn-education"],
            )
            section_buttons["personal_history"] = gr.Button(
                "Personal History",
                elem_classes=["section-button", "btn-personal-history"],
            )
            section_buttons["phq9"] = gr.Button(
                "PHQ-9",
                elem_classes=["section-button", "btn-phq9"],
            )
            section_buttons["gad7"] = gr.Button(
                "GAD-7",
                elem_classes=["section-button", "btn-gad7"],
            )

        with gr.Row(elem_classes="main-content-row"):
            with gr.Column(scale=2, min_width=520, elem_classes="chat-shell"):
                chatbot = gr.Chatbot(
                    height=560,
                    show_label=False,
                    avatar_images=(USER_AVATAR, ALICE_AVATAR),
                )

                msg = gr.Textbox(
                    placeholder="Type your message here...",
                    show_label=False,
                    container=False,
                )

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

                alice_audio_output = gr.Audio(
                    autoplay=True,
                    interactive=False,
                    show_label=False,
                    container=False,
                    elem_id="alice-audio-output",
                )

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

            with gr.Column(scale=1, min_width=320, elem_classes="info-shell"):
                info_display = gr.HTML(
                    value=format_display(None),
                    elem_classes="info-box",
                    label="Collected Information",
                )

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

        msg.submit(
            chat,
            inputs=[msg, chatbot, alice_state, alice_voice_enabled, patient_voice_enabled],
            outputs=[chatbot, alice_state, info_display, alice_audio_output],
        ).then(lambda: "", outputs=msg)

        for section_name, button in section_buttons.items():
            button.click(
                make_switch_handler(section_name),
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
