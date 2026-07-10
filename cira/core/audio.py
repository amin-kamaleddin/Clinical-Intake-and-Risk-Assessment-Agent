import os
import tempfile

from openai import OpenAI

from core.config import STT_MODEL, TTS_MODEL, TTS_VOICE


openai_client = OpenAI()


def text_to_speech(text):
    """Convert an ALICE text response into a temporary MP3 file."""
    if not text or not str(text).strip():
        return None

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    temp_file.close()

    try:
        response = openai_client.audio.speech.create(
            model=TTS_MODEL,
            voice=TTS_VOICE,
            input=str(text),
            instructions=(
                "Speak with a warm, friendly, young adult feminine voice. "
                "Sound calm, caring, natural, and professional. "
                "Use a comfortable and clear speaking pace."
            ),
        )
        response.write_to_file(temp_file.name)
        return temp_file.name

    except Exception as error:
        print(f"Text-to-speech error: {error}")
        try:
            os.remove(temp_file.name)
        except OSError:
            pass
        return None


def transcribe_audio(audio_file):
    """Transcribe a patient recording, preserving spelled-out identifiers."""
    if not audio_file:
        return None

    try:
        with open(audio_file, "rb") as audio:
            transcription = openai_client.audio.transcriptions.create(
                model=STT_MODEL,
                file=audio,
                prompt=(
                    "This is a Canadian clinical intake conversation. "
                    "The speaker may provide personal names, doctor names, "
                    "street names, city names, postal codes, dates, phone "
                    "numbers, and email addresses. The speaker may spell "
                    "names letter by letter. Preserve every spelled letter "
                    "carefully and do not combine or correct the letters."
                ),
            )
        return transcription.text.strip()

    except Exception as error:
        print(f"Speech-to-text error: {error}")
        return None
