import os
import tempfile

from PIL import Image, ImageDraw


# ── Avatars ────────────────────────────────────────────────────────────────────

def make_avatar(color: tuple, size: int = 80) -> str:
    """Generate a plain circular avatar PNG and return its temp file path."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw  = ImageDraw.Draw(image)
    draw.ellipse([0, 0, size - 1, size - 1], fill=color)
    path  = os.path.join(tempfile.gettempdir(), f"avatar_{color[0]}.png")
    image.save(path)
    return path


ALICE_AVATAR = "https://img.icons8.com/color/96/nurse-female.png"
USER_AVATAR  = make_avatar((99, 115, 129))


# ── CSS ────────────────────────────────────────────────────────────────────────

CUSTOM_CSS = """
@import url(
    'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap'
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
    max-width: 1180px !important;
    margin: 0 auto !important;
    padding: 24px !important;
}

.alice-header {
    display: flex;
    align-items: center;
    gap: 16px;
    background: white;
    border: 1px solid #c5d8f0;
    border-radius: 14px;
    padding: 20px 26px;
    margin-bottom: 16px;
}

.alice-header h1 {
    color: #1e293b !important;
    font-size: 22px !important;
    font-weight: 600 !important;
    margin: 0 !important;
    padding: 0 !important;
}

.alice-header p {
    color: #64748b !important;
    font-size: 13px !important;
    margin: 3px 0 0 !important;
}

.btn-general button,
.btn-concerns button {
    width: 100% !important;
    padding: 14px 20px !important;
    border-radius: 10px !important;
    background: white !important;
    color: #1e293b !important;
    font-size: 14px !important;
    font-weight: 500 !important;
    text-align: left !important;
    box-shadow: none !important;
    transition: background 0.15s ease !important;
}

.btn-general button {
    border: 1px solid #c5d8f0 !important;
    border-left: 3px solid #185FA5 !important;
}

.btn-concerns button {
    border: 1px solid #c5d8f0 !important;
    border-left: 3px solid #0F6E56 !important;
}

.btn-general button:hover,
.btn-concerns button:hover {
    background: #f0f6ff !important;
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

/*
The ALICE audio element remains rendered so autoplay can work,
but the player controls are not shown.
*/
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
    background: #f0f6ff !important;
    border: 1px solid #c5d8f0 !important;
    border-radius: 14px !important;
    padding: 18px !important;
}

.empty-info {
    padding: 20px;
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

.information-title {
    color: #1e40af;
    font-size: 13px;
    font-weight: 600;
}

.information-count {
    color: #94a3b8;
    font-size: 11px;
}

.progress-track {
    height: 5px;
    margin-bottom: 16px;
    overflow: hidden;
    border-radius: 999px;
    background: #e2e8f0;
}

.progress-value {
    height: 5px;
    border-radius: 999px;
    background: linear-gradient(90deg, #185FA5, #3b82f6);
}

.info-field {
    padding: 11px 0;
    border-bottom: 1px solid #e8f0fb;
}

.field-label {
    margin-bottom: 5px;
    color: #94a3b8;
    font-size: 10px;
    letter-spacing: 0.6px;
    text-transform: uppercase;
}

.field-value {
    color: #1e293b;
    font-size: 14px;
    font-weight: 500;
    overflow-wrap: anywhere;
}

.field-empty {
    color: #cbd5e0;
    font-size: 13px;
    font-style: italic;
}

.boolean-badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
}

.yes-badge {
    color: #0F6E56;
    background: #e6f4ef;
}

.no-badge {
    color: #718096;
    background: #f1f5f9;
}

@media (max-width: 760px) {
    .gradio-container {
        padding: 12px !important;
    }

    .alice-header {
        padding: 16px 18px;
    }
}
"""
