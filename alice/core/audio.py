import os
import tempfile

from openai import OpenAI


# Shared client — reads OPENAI_API_KEY from the environment.
openai_client = OpenAI()


def text_to_speech(text: str) -> str | None:
    """
    Convert an ALICE text response into a temporary MP3 file.
    Returns the file path, or None on empty input / failure.
    """
    if not text or not str(text).strip():
        return None

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    temp_file.close()

    try:
        response = openai_client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice="shimmer",
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


def transcribe_audio(audio_file: str) -> str | None:
    """
    Transcribe a patient recording into text.
    The prompt biases the model toward preserving spelled-out names and
    clinical identifiers letter by letter. Returns text, or None on failure.
    """
    if not audio_file:
        return None

    try:
        with open(audio_file, "rb") as audio:
            transcription = openai_client.audio.transcriptions.create(
                model="gpt-4o-transcribe",
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
