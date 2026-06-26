import os
import tempfile

from PIL import Image, ImageDraw


def make_avatar(color, size=80):
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse([0, 0, size - 1, size - 1], fill=color)
    path = os.path.join(
        tempfile.gettempdir(),
        f"avatar_{color[0]}_{color[1]}_{color[2]}.png",
    )
    image.save(path)
    return path


ALICE_AVATAR = "https://img.icons8.com/color/96/nurse-female.png"
USER_AVATAR = make_avatar((99, 115, 129))


CUSTOM_CSS = """
@import url(
    'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap'
);

*, body, .gradio-container {
    font-family:
        'Inter',
        -apple-system,
        BlinkMacSystemFont,
        sans-serif !important;
}

body,
.gradio-container {
    background: #dce8f5 !important;
}

.gradio-container {
    max-width: 1280px !important;
    margin: 0 auto !important;
    padding: 24px !important;
}

.alice-header {
    display: flex;
    align-items: center;
    gap: 16px;
    background: white;
    border: 1px solid #c5d8f0;
    border-radius: 16px;
    padding: 20px 26px;
    margin-bottom: 14px;
    box-shadow: 0 8px 24px rgba(30, 64, 175, 0.06);
}

.alice-header h1 {
    color: #1e293b !important;
    font-size: 23px !important;
    font-weight: 700 !important;
    margin: 0 !important;
    padding: 0 !important;
}

.alice-header p {
    color: #64748b !important;
    font-size: 13px !important;
    margin: 3px 0 0 !important;
}

.section-nav-label {
    margin: 2px 2px 8px;
    color: #475569;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.45px;
    text-transform: uppercase;
}

.section-nav-row {
    gap: 10px !important;
    margin-bottom: 10px;
}

.section-button button {
    width: 100% !important;
    min-height: 52px !important;
    padding: 11px 14px !important;
    border: 1px solid #c5d8f0 !important;
    border-radius: 11px !important;
    background: white !important;
    color: #1e293b !important;
    font-size: 12px !important;
    font-weight: 600 !important;
    line-height: 1.25 !important;
    text-align: left !important;
    box-shadow: none !important;
    transition:
        transform 0.15s ease,
        background 0.15s ease,
        border-color 0.15s ease !important;
}

.section-button button:hover {
    background: #f8fbff !important;
    border-color: #93b4dc !important;
    transform: translateY(-1px);
}

.btn-general button { border-left: 4px solid #185FA5 !important; }
.btn-concerns button { border-left: 4px solid #0F6E56 !important; }
.btn-history button { border-left: 4px solid #7c3aed !important; }
.btn-medications button { border-left: 4px solid #d97706 !important; }
.btn-medical-history button { border-left: 4px solid #0284c7 !important; }
.btn-allergies button { border-left: 4px solid #dc2626 !important; }
.btn-family-history button { border-left: 4px solid #9333ea !important; }
.btn-substance-use button { border-left: 4px solid #0f766e !important; }
.btn-education button { border-left: 4px solid #4f46e5 !important; }
.btn-personal-history button { border-left: 4px solid #be123c !important; }
.btn-phq9 button { border-left: 4px solid #2563eb !important; }
.btn-gad7 button { border-left: 4px solid #0891b2 !important; }

.main-content-row {
    margin-top: 8px;
    align-items: stretch !important;
}

.chat-shell,
.info-shell {
    min-width: 0 !important;
}

.voice-card {
    min-height: 132px;
    background: white !important;
    border: 1px solid #c5d8f0 !important;
    border-radius: 12px !important;
    padding: 14px !important;
}

.voice-title {
    margin-bottom: 8px;
    color: #334155;
    font-size: 13px;
    font-weight: 600;
}

.voice-description {
    min-height: 34px;
    color: #64748b;
    font-size: 12px;
    line-height: 1.45;
}

.alice-voice-button button {
    border: 1px solid #93c5fd !important;
    background: #eff6ff !important;
    color: #1d4ed8 !important;
}

.patient-voice-button button {
    border: 1px solid #86efac !important;
    background: #f0fdf4 !important;
    color: #166534 !important;
}

#alice-audio-output {
    display: none !important;
}

.patient-recorder {
    margin-top: 8px !important;
}

.patient-status {
    color: #64748b;
    font-size: 12px;
}

.ai-disclosure {
    color: #64748b;
    font-size: 11px;
    margin-top: 4px;
}

.info-box {
    height: 100%;
    max-height: 760px;
    overflow-y: auto;
    background: #f8fbff !important;
    border: 1px solid #c5d8f0 !important;
    border-radius: 14px !important;
    padding: 18px !important;
}

.empty-info {
    padding: 36px 20px;
    color: #94a3b8;
    font-size: 13px;
    font-style: italic;
    text-align: center;
}

.information-panel {
    padding: 4px 8px;
}

.information-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;
    padding-bottom: 12px;
    border-bottom: 2px solid #dbeafe;
}

.information-kicker {
    margin-bottom: 3px;
    color: #94a3b8;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.85px;
}

.information-title {
    color: #1e40af;
    font-size: 14px;
    font-weight: 700;
}

.information-count {
    color: #64748b;
    font-size: 11px;
    font-weight: 600;
}

.progress-track {
    height: 6px;
    margin-bottom: 16px;
    overflow: hidden;
    border-radius: 999px;
    background: #e2e8f0;
}

.progress-value {
    height: 6px;
    border-radius: 999px;
    background: linear-gradient(90deg, #185FA5, #3b82f6);
    transition: width 0.25s ease;
}

.info-field {
    padding: 11px 0;
    border-bottom: 1px solid #e8f0fb;
}

.field-label {
    margin-bottom: 5px;
    color: #94a3b8;
    font-size: 10px;
    letter-spacing: 0.55px;
    text-transform: uppercase;
}

.field-value {
    color: #1e293b;
    font-size: 14px;
    font-weight: 500;
    line-height: 1.5;
    overflow-wrap: anywhere;
    white-space: pre-wrap;
}

.field-empty {
    color: #cbd5e1;
    font-size: 13px;
    font-style: italic;
}

.boolean-badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
}

.yes-badge {
    color: #0F6E56;
    background: #e6f4ef;
}

.no-badge {
    color: #64748b;
    background: #eef2f7;
}

.score-value {
    display: inline-flex;
    min-width: 42px;
    height: 34px;
    align-items: center;
    justify-content: center;
    border-radius: 10px;
    background: #dbeafe;
    color: #1e40af;
    font-size: 17px;
    font-weight: 700;
}

@media (max-width: 900px) {
    .gradio-container { padding: 14px !important; }
    .section-nav-row { flex-wrap: wrap !important; }
    .section-button { min-width: calc(50% - 8px) !important; }
    .info-box { max-height: none; }
}

@media (max-width: 600px) {
    .gradio-container { padding: 10px !important; }
    .alice-header { padding: 16px 18px; }
    .section-button { min-width: 100% !important; }
}
"""
