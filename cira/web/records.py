"""Keep a copy of every record somewhere that outlives the server.

A free instance has no disk worth the name: Render discards filesystem changes
whenever the service sleeps, and a container's filesystem goes with the
container. core.storage still writes each record locally after every turn -
that is the agent's own behaviour and it is untouched - and this module copies
it out to a private GitHub repository, which costs nothing and is somewhere a
person can actually read it.

Configure it with:

    CIRA_RECORD_REPO     owner/name of a PRIVATE repository          (required)
    CIRA_RECORD_TOKEN    token with Contents: read and write         (required)
    CIRA_RECORD_BRANCH   default "main"
    CIRA_RECORD_PREFIX   directory inside the repo, default "records"
    CIRA_RECORD_FLUSH    seconds between uploads, default 60

Leave CIRA_RECORD_REPO unset and nothing here runs.

Two things this is not. It is not a clinical record system: a git repository
keeps what you delete, so a record committed here cannot truly be withdrawn,
and real patient data belongs in storage that supports deletion, encryption
and an access log. And the repository must be private - a public one publishes
every intake to the world.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import threading
import time

import httpx

#: session id -> the most recent record for that session, not yet uploaded.
#: One entry per session, replaced rather than appended, so a long intake
#: costs one upload per flush instead of one per answer.
_pending: dict[str, dict] = {}

#: session id -> the blob sha GitHub last gave us for that file. Updating a
#: file requires the sha it is replacing; caching it means one extra request
#: per session rather than one before every upload.
_blob_sha: dict[str, str] = {}

_lock = threading.Lock()
_started = False


# --------------------------------------------------------------------------- #
# configuration
# --------------------------------------------------------------------------- #
def _repo() -> str:
    return os.getenv("CIRA_RECORD_REPO", "").strip()


def _token() -> str:
    return os.getenv("CIRA_RECORD_TOKEN", "").strip()


def _branch() -> str:
    return os.getenv("CIRA_RECORD_BRANCH", "main").strip()


def _prefix() -> str:
    return os.getenv("CIRA_RECORD_PREFIX", "records").strip().strip("/")


def _interval() -> float:
    try:
        return max(5.0, float(os.getenv("CIRA_RECORD_FLUSH", "60")))
    except ValueError:
        return 60.0


def _api() -> str:
    """The API root. Overridable for GitHub Enterprise, and for testing."""
    return os.getenv("CIRA_RECORD_API", "https://api.github.com").rstrip("/")


def enabled() -> bool:
    return bool(_repo() and _token())


def _log(message: str) -> None:
    # Loud, because the failure mode is silent: records stop being kept and
    # nothing about the intake itself looks wrong.
    print(f"[cira] record upload: {message}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# uploading
# --------------------------------------------------------------------------- #
def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _path(session_id: str) -> str:
    return f"{_prefix()}/{session_id}.json" if _prefix() else f"{session_id}.json"


def _contents_url(session_id: str) -> str:
    return f"{_api()}/repos/{_repo()}/contents/{_path(session_id)}"


def _fetch_sha(client: httpx.Client, session_id: str) -> str | None:
    """The sha of the file already in the repository, if there is one."""
    response = client.get(
        _contents_url(session_id),
        headers=_headers(),
        params={"ref": _branch()},
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json().get("sha")


def _upload(client: httpx.Client, session_id: str, record: dict) -> None:
    """Write one record, creating the file or replacing what is there.

    A 409 means the sha we held is stale - something else wrote the file
    between our read and our write - so the sha is re-read once and the write
    retried. Beyond that the record stays pending and the next flush tries
    again.
    """
    body = json.dumps(record, indent=2, ensure_ascii=False, default=str)
    payload = {
        "message": f"intake {session_id}",
        "content": base64.b64encode(body.encode("utf-8")).decode("ascii"),
        "branch": _branch(),
    }

    for attempt in (1, 2):
        sha = _blob_sha.get(session_id)
        if sha is None:
            sha = _fetch_sha(client, session_id)
        if sha is not None:
            payload["sha"] = sha
        else:
            payload.pop("sha", None)

        response = client.put(_contents_url(session_id), headers=_headers(), json=payload)

        if response.status_code in (200, 201):
            _blob_sha[session_id] = response.json()["content"]["sha"]
            return

        if response.status_code == 409 and attempt == 1:
            _blob_sha.pop(session_id, None)
            continue

        response.raise_for_status()


def _flush() -> None:
    """Upload every record that has changed since the last flush."""
    with _lock:
        batch = dict(_pending)
        _pending.clear()

    if not batch:
        return

    failed: dict[str, dict] = {}
    with httpx.Client(timeout=30.0) as client:
        for session_id, record in batch.items():
            try:
                _upload(client, session_id, record)
            except Exception as error:            # noqa: BLE001 - see below
                # Deliberately broad: a network error, a revoked token and a
                # deleted repository all mean the same thing here, which is
                # that this record must be kept and tried again. Nothing about
                # an upload is worth ending a patient's intake over.
                _log(f"{session_id}: {error}")
                failed[session_id] = record

    if failed:
        with _lock:
            # Anything written during the upload wins - it is newer.
            for session_id, record in failed.items():
                _pending.setdefault(session_id, record)


def _flush_forever() -> None:
    while True:
        time.sleep(_interval())
        try:
            _flush()
        except Exception as error:               # noqa: BLE001
            _log(f"flush failed: {error}")


# --------------------------------------------------------------------------- #
# what the server calls
# --------------------------------------------------------------------------- #
def start() -> None:
    """Begin flushing in the background, once, if this is configured."""
    global _started
    if _started or not enabled():
        return
    _started = True
    threading.Thread(target=_flush_forever, daemon=True, name="cira-records").start()
    _log(f"keeping records in {_repo()} every {_interval():.0f}s")


def remember(record: dict, urgent: bool = False) -> None:
    """Queue a record for upload, or send it immediately.

    Called after every turn. Queuing rather than uploading is what keeps a
    seventy-field intake from becoming seventy commits.

    ``urgent`` skips the wait. It is used when the safety flag is raised,
    because that is the one record whose loss to a sleeping instance actually
    matters, and it is worth a request of its own.
    """
    if not enabled():
        return

    session_id = record.get("session_id")
    if not session_id:
        return

    with _lock:
        _pending[session_id] = record

    if urgent:
        # In a thread, so a patient disclosing risk never waits on a network
        # round trip to see CIRA's reply.
        threading.Thread(target=_flush, daemon=True, name="cira-records-now").start()
