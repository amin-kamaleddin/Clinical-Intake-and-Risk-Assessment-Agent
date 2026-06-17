import os
import tempfile

from PIL import Image, ImageDraw


# ── Avatars ────────────────────────────────────────────────────────────────────

ALICE_AVATAR = "https://img.icons8.com/color/96/nurse-female.png"


def make_avatar(color: tuple, size: int = 80) -> str:
    """Generate a plain circular avatar PNG and return its temp file path."""
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([0, 0, size - 1, size - 1], fill=color)
    path = os.path.join(tempfile.gettempdir(), f"avatar_{color[0]}.png")
    img.save(path)
    return path


USER_AVATAR = make_avatar((99, 115, 129))


# ── CSS ────────────────────────────────────────────────────────────────────────

CUSTOM_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');

*, body, .gradio-container {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}

body, .gradio-container {
    background: #dce8f5 !important;
}

.gradio-container {
    max-width: 1150px !important;
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
    font-size: 22px !important;
    font-weight: 600 !important;
    color: #1e293b !important;
    margin: 0 !important;
    padding: 0 !important;
    font-family: 'Inter', sans-serif !important;
}

.alice-header p {
    font-size: 13px !important;
    color: #64748b !important;
    margin: 3px 0 0 !important;
}

.btn-general button, .btn-concerns button {
    width: 100% !important;
    padding: 14px 20px !important;
    border-radius: 10px !important;
    font-size: 14px !important;
    font-weight: 500 !important;
    background: white !important;
    color: #1e293b !important;
    text-align: left !important;
    box-shadow: none !important;
    font-family: 'Inter', sans-serif !important;
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

.btn-general button:hover, .btn-concerns button:hover {
    background: #f0f6ff !important;
}

.info-box {
    background: #f0f6ff !important;
    border: 1px solid #c5d8f0 !important;
    border-radius: 14px !important;
    padding: 18px !important;
}
"""
