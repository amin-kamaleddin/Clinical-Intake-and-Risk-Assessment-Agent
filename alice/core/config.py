import os

# Model names — overridable via environment for reproducible eval runs.
MODEL_NAME       = os.getenv("ALICE_MODEL", "gpt-5.4-mini")
EVAL_TEMPERATURE = 0
STT_MODEL        = os.getenv("ALICE_STT_MODEL", "gpt-4o-transcribe")
TTS_MODEL        = os.getenv("ALICE_TTS_MODEL", "gpt-4o-mini-tts")
TTS_VOICE        = os.getenv("ALICE_TTS_VOICE", "shimmer")

SUPPORTED_TEST_LANGUAGES = ["English", "French", "Hindi"]
