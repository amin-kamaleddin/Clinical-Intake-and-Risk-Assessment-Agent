"""HTTP backend for the CIRA intake interface.

One FastAPI service: it serves the interface and exposes the agent behind a
small JSON API. One service means one thing to deploy, and the LangGraph agent
stays exactly as the evaluation validated it - nothing here reaches into the
graph, it only prepares state and reads results.

    python -m cira.web.server          # http://127.0.0.1:8000

Sessions live in memory, keyed by a random id the browser holds: an intake is
one sitting. core.storage writes the record to ``records/<session_id>.json``
after every turn, relative to the directory the server was started in, so start
the server where those records should land. On a host whose filesystem does not
survive a restart, set CIRA_RECORD_REPO as well and web.records keeps a copy
somewhere that does.

Those files carry a name, a date of birth, a home address, a phone number and
psychiatric history. The only correct home for them is storage that is backed
up, access-controlled, and covered by your institution's privacy rules.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

CIRA_ROOT = Path(__file__).resolve().parent.parent
if str(CIRA_ROOT) not in sys.path:
    sys.path.insert(0, str(CIRA_ROOT))

from dotenv import load_dotenv

load_dotenv(CIRA_ROOT / ".env")

from fastapi import FastAPI, HTTPException, UploadFile, File, Form  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from core.audio import text_to_speech, transcribe_audio  # noqa: E402
from core.languages import EVALUATION_LANGUAGES, get, safety_reply_for  # noqa: E402
from core.safety import SAFETY_REPLY  # noqa: E402
from core.state import initial_state  # noqa: E402
from graph.builder import graph  # noqa: E402
from ui.schema import (  # noqa: E402
    SECTION_TITLES, FIELD_LABELS, normalize_state_schema, should_show_field,
)
from web import records  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"


app = FastAPI(title="CIRA", docs_url=None, redoc_url=None)

#: session id -> agent state. See the module docstring on why this is in memory.
SESSIONS: dict[str, dict] = {}



# --------------------------------------------------------------------------- #
# request bodies
# --------------------------------------------------------------------------- #
class StartBody(BaseModel):
    language: str = "English"


class MessageBody(BaseModel):
    session: str
    text: str


class SectionBody(BaseModel):
    session: str
    section: str


class LanguageBody(BaseModel):
    session: str
    language: str


class SpeakBody(BaseModel):
    session: str
    text: str


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _session(session_id: str) -> dict:
    state = SESSIONS.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found. Reload to start a new one.")
    return state


def _render_value(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _snapshot(state: dict) -> dict:
    """Everything the interface needs to draw itself after a turn.

    Sent as data rather than as HTML so the browser owns presentation entirely;
    the server never decides what a field looks like, only what it holds.
    """
    state = normalize_state_schema(state)
    language = state.get("preferred_language", "English")

    sections = []
    for key, title in SECTION_TITLES.items():
        data = state.get(key) or {}
        labels = FIELD_LABELS.get(key, {})
        fields, filled = [], 0
        for field, label in labels.items():
            # Reuses the record panel's own rule so a detail field the
            # patient answered "no" to never shows up as an empty gap.
            if not should_show_field(field, data):
                continue
            value = _render_value(data.get(field))
            if value is not None:
                filled += 1
            fields.append({"label": label, "value": value})
        sections.append({
            "key": key,
            "title": title,
            "fields": fields,
            "filled": filled,
            "total": len(fields),
            "complete": key in (state.get("sections_completed") or []),
            "active": key == state.get("current_section"),
        })

    total_fields = sum(s["total"] for s in sections)
    total_filled = sum(s["filled"] for s in sections)

    return {
        "session": state.get("session_id"),
        "language": language,
        "rtl": language in {"Arabic", "Farsi"},
        "current_section": state.get("current_section"),
        "sections": sections,
        "progress": {
            "filled": total_filled,
            "total": total_fields,
            "sections_done": len(state.get("sections_completed") or []),
            "sections_total": len(SECTION_TITLES),
        },
        # The banner repeats the agent's own crisis wording, so the screen says
        # one thing rather than two.
        "safety": {
            "flagged": bool(state.get("safety_flag")),
            "message": safety_reply_for(language, SAFETY_REPLY),
        },
    }


def _record(state: dict) -> dict:
    """The intake answers alone - no transcript, no interface bookkeeping."""
    skip = {"messages", "latest_input_source", "speech_to_text_active"}
    return {key: value for key, value in state.items() if key not in skip}


def _advance(state: dict) -> tuple[dict, str]:
    """Run one agent turn and return the new state with CIRA's reply."""
    was_flagged = bool(state.get("safety_flag"))

    state = normalize_state_schema(graph.invoke(state))
    reply = ""
    for message in reversed(state.get("messages") or []):
        if message.get("role") == "assistant":
            reply = message.get("content") or ""
            break

    # Queued rather than uploaded: see web.records on why a seventy-field
    # intake must not become seventy commits. A newly raised flag goes at once.
    records.remember(
        _record(state),
        urgent=bool(state.get("safety_flag")) and not was_flagged,
    )
    return state, reply


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
@app.get("/api/languages")
def languages():
    return [
        {"value": name, "label": name, "native": get(name).native_name,
         "rtl": name in {"Arabic", "Farsi"}}
        for name in EVALUATION_LANGUAGES
    ]


@app.post("/api/session")
def start_session(body: StartBody):
    state = normalize_state_schema(copy.deepcopy(initial_state))
    state["session_id"] = uuid.uuid4().hex[:12]
    state["preferred_language"] = body.language
    SESSIONS[state["session_id"]] = state
    return {"snapshot": _snapshot(state), "reply": None}


@app.post("/api/section")
def open_section(body: SectionBody):
    if body.section not in SECTION_TITLES:
        raise HTTPException(status_code=400, detail="Unknown section.")
    state = _session(body.session)
    state["current_section"] = body.section
    state, reply = _advance(state)
    SESSIONS[body.session] = state
    return {"snapshot": _snapshot(state), "reply": reply}


@app.post("/api/message")
def send_message(body: MessageBody):
    state = _session(body.session)
    text = (body.text or "").strip()
    if not text:
        return {"snapshot": _snapshot(state), "reply": None}
    if state.get("current_section") is None:
        return {"snapshot": _snapshot(state), "reply": None,
                "notice": "Choose a section to begin."}

    state["latest_input_source"] = "typed text"
    state["messages"] = (state.get("messages") or []) + [{"role": "user", "content": text}]
    state, reply = _advance(state)
    SESSIONS[body.session] = state
    return {"snapshot": _snapshot(state), "reply": reply}


@app.post("/api/language")
def set_language(body: LanguageBody):
    """Switch language mid-session.

    The RECORD is unaffected - CIRA stores every value in English whatever the
    conversation language - so a switch cannot split one record across two
    languages.
    """
    state = _session(body.session)
    state["preferred_language"] = body.language
    SESSIONS[body.session] = state
    return {"snapshot": _snapshot(state)}


@app.post("/api/transcribe")
async def transcribe(session: str = Form(...), audio: UploadFile = File(...)):
    state = _session(session)
    if state.get("current_section") is None:
        return {"text": None, "notice": "Choose a section to begin."}
    language = state.get("preferred_language", "English")

    suffix = Path(audio.filename or "clip.webm").suffix or ".webm"
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    handle.write(await audio.read())
    handle.close()
    try:
        # Transcribed WITH the language rather than by detection: a one-word
        # answer gives a detector almost nothing, and a wrong guess returns
        # fluent nonsense rather than an error.
        text = transcribe_audio(handle.name, language)
    finally:
        os.unlink(handle.name)

    if not text:
        return {"text": None}

    state["latest_input_source"] = "speech-to-text"
    state["speech_to_text_active"] = True
    state["messages"] = (state.get("messages") or []) + [{"role": "user", "content": text}]
    state, reply = _advance(state)
    SESSIONS[session] = state
    return {"text": text, "snapshot": _snapshot(state), "reply": reply}


@app.post("/api/speak")
def speak(body: SpeakBody):
    state = _session(body.session)
    path = text_to_speech(body.text, state.get("preferred_language", "English"))
    if not path:
        raise HTTPException(status_code=503, detail="Speech is unavailable.")
    return FileResponse(path, media_type="audio/mpeg", filename="cira.mp3")


@app.get("/api/record/{session_id}")
def download_record(session_id: str):
    """Export the record as JSON.

    Served to the clinician rather than written into the project: this holds a
    name, date of birth, home address, phone number and psychiatric history, and
    a source directory is the wrong place for it to accumulate.
    """
    state = _session(session_id)
    record = _record(state)
    handle = tempfile.NamedTemporaryFile(
        delete=False, suffix=".json", prefix=f"cira_{session_id}_",
        mode="w", encoding="utf-8",
    )
    json.dump(record, handle, indent=2, ensure_ascii=False)
    handle.close()
    return FileResponse(handle.name, media_type="application/json",
                        filename=f"cira_{session_id}.json")


@app.get("/api/health")
def health():
    return JSONResponse({"status": "ok", "sessions": len(SESSIONS)})


# Starts the background uploader, or does nothing if no repository is
# configured. Here rather than in a startup hook because this module is the
# application: importing it is what brings the service into being.
records.start()

app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("CIRA_HOST", "127.0.0.1"),
        port=int(os.getenv("CIRA_PORT", "8000")),
    )
