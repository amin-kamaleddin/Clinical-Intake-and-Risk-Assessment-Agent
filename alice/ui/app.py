import gradio as gr

from ui.styles import CUSTOM_CSS, ALICE_AVATAR, USER_AVATAR
from ui.display import format_display
from ui.handlers import start, chat, switch_section


def build_demo() -> gr.Blocks:
    with gr.Blocks(title="ALICE", css=CUSTOM_CSS, theme=gr.themes.Soft()) as demo:

        alice_state = gr.State(None)

        # ── Header ─────────────────────────────────────────────────────────────
        gr.HTML("""
            <div class="alice-header">
                <div style="width:52px;height:52px;border-radius:50%;background:#dbeafe;
                            display:flex;align-items:center;justify-content:center;
                            font-size:26px;flex-shrink:0;">👩‍⚕️</div>
                <div>
                    <h1>Alice</h1>
                    <p>Clinical Intake Assistant</p>
                </div>
            </div>
        """)

        # ── Section buttons ─────────────────────────────────────────────────────
        with gr.Row():
            btn_general  = gr.Button("General Information", elem_classes="btn-general")
            btn_concerns = gr.Button("Current Concerns",    elem_classes="btn-concerns")

        # ── Main layout: chat + info panel ──────────────────────────────────────
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

            with gr.Column(scale=1):
                info_display = gr.HTML(
                    value=format_display(None),
                    elem_classes="info-box",
                    label="Collected Information",
                )

        # ── Event wiring ────────────────────────────────────────────────────────
        msg.submit(
            chat,
            inputs=[msg, chatbot, alice_state],
            outputs=[chatbot, alice_state, info_display],
        ).then(lambda: "", outputs=msg)

        btn_general.click(
            lambda s: switch_section("general_information", s),
            inputs=[alice_state],
            outputs=[chatbot, alice_state, info_display],
        )

        btn_concerns.click(
            lambda s: switch_section("current_concerns", s),
            inputs=[alice_state],
            outputs=[chatbot, alice_state, info_display],
        )

        demo.load(start, inputs=[], outputs=[chatbot, alice_state, info_display])

    return demo


demo = build_demo()
