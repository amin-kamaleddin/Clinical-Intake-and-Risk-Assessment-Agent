import os
from pathlib import Path

from dotenv import load_dotenv
# Model names — overridable via environment for reproducible eval runs.
MODEL_NAME       = os.getenv("CIRA_MODEL", "gpt-5.5")

STT_MODEL        = os.getenv("CIRA_STT_MODEL", "gpt-4o-transcribe")
TTS_MODEL        = os.getenv("CIRA_TTS_MODEL", "gpt-4o-mini-tts")
TTS_VOICE        = os.getenv("CIRA_TTS_VOICE", "shimmer")

SUPPORTED_TEST_LANGUAGES = ["English", "French", "Hindi"]



PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(dotenv_path=ENV_FILE)
