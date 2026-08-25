import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(dotenv_path=ENV_FILE)

# Model names — overridable via environment for reproducible eval runs.
MODEL_NAME       = os.getenv("CIRA_MODEL", "gpt-5.6-luna")

# Sampling temperature for CIRA's own model.
#
# This MUST be set explicitly. Leaving it unset sends no temperature at all and
# the provider default (1.0) applies, which meant the benchmark compared CIRA at
# ~1.0 against the prompt-only baseline pinned at 0.0 — a sampling difference
# reported as an architecture difference. It also made CIRA the only stochastic
# component in an otherwise pinned pipeline, so no case reproduced on a re-run.
#
# Keep this equal to CIRA_NAIVE_TEMPERATURE. The two arms share an underlying
# model and the comparison is only interpretable when they share sampling too.
TEMPERATURE      = float(os.getenv("CIRA_TEMPERATURE", "0"))

STT_MODEL        = os.getenv("CIRA_STT_MODEL", "gpt-4o-transcribe")
TTS_MODEL        = os.getenv("CIRA_TTS_MODEL", "gpt-4o-mini-tts")
TTS_VOICE        = os.getenv("CIRA_TTS_VOICE", "shimmer")

SUPPORTED_TEST_LANGUAGES = ["English", "French", "Hindi"]

