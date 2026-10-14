"""Regression tests for web.records, the off-box copy of each intake record.

    cd cira
    python -m tests.test_record_upload

Offline and no keys: a stand-in for the GitHub Contents API runs on localhost
and enforces the two rules that actually bite in production - a new file must
carry no sha, and replacing a file must carry the sha it replaces.

What is worth pinning here is not that an upload works. It is that one intake
costs one upload per flush rather than one per answer, that a stale sha is
recovered instead of losing the record, and that a failed upload is kept and
tried again. Each of those fails silently: the intake looks fine and the
records simply stop arriving.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8711
PASSED = 0
FAILURES: list[str] = []


# --------------------------------------------------------------------------- #
# a stand-in for the GitHub Contents API
# --------------------------------------------------------------------------- #
FILES: dict[str, tuple[str, str]] = {}      # path -> (sha, content)
CALLS: list[tuple[str, str, int]] = []      # (method, path, status)


def _blob_sha(body: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass                                 # the test prints what matters

    def _send(self, status, payload=None):
        body = json.dumps(payload or {}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file_path(self):
        return self.path.split("/contents/", 1)[1].split("?")[0]

    def _authorized(self):
        return self.headers.get("Authorization", "").startswith("Bearer ")

    #: Set to a status code to make the repository lookup fail, as an expired
    #: token or a deleted repository would.
    repo_status = 200
    repo_private = True

    def do_GET(self):
        # The repository lookup that _verify() makes, as opposed to a file read.
        if "/contents/" not in self.path:
            CALLS.append(("GET", "repo", self.repo_status))
            if self.repo_status != 200:
                return self._send(self.repo_status, {"message": "nope"})
            return self._send(200, {"private": self.repo_private})

        path = self._file_path()
        if not self._authorized():
            CALLS.append(("GET", path, 401))
            return self._send(401, {"message": "Bad credentials"})
        if path not in FILES:
            CALLS.append(("GET", path, 404))
            return self._send(404, {"message": "Not Found"})
        CALLS.append(("GET", path, 200))
        self._send(200, {"sha": FILES[path][0]})

    def do_PUT(self):
        path = self._file_path()
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

        if not self._authorized():
            CALLS.append(("PUT", path, 401))
            return self._send(401, {"message": "Bad credentials"})

        content = base64.b64decode(payload["content"]).decode("utf-8")
        existing = FILES.get(path)
        given = payload.get("sha")

        if existing is None and given is not None:
            CALLS.append(("PUT", path, 422))
            return self._send(422, {"message": "sha given for a new file"})
        if existing is not None and given != existing[0]:
            CALLS.append(("PUT", path, 409))
            return self._send(409, {"message": "sha does not match"})

        sha = _blob_sha(content.encode())
        FILES[path] = (sha, content)
        status = 200 if existing else 201
        CALLS.append(("PUT", path, status))
        self._send(status, {"content": {"sha": sha, "path": path}})


# --------------------------------------------------------------------------- #
# checks
# --------------------------------------------------------------------------- #
def check(label, condition, detail=""):
    global PASSED
    if condition:
        PASSED += 1
        print(f"  ok    {label}")
    else:
        FAILURES.append(label)
        print(f"  FAIL  {label}" + (f"  [{detail}]" if detail else ""))


def puts():
    return [call for call in CALLS if call[0] == "PUT"]


def gets():
    return [call for call in CALLS if call[0] == "GET"]


def main():
    os.environ["CIRA_RECORD_REPO"] = "example/cira-records"
    os.environ["CIRA_RECORD_TOKEN"] = "test-token"
    os.environ["CIRA_RECORD_API"] = f"http://127.0.0.1:{PORT}"

    from web import records

    server = HTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.3)

    path = "records/abc123.json"

    print("\nconfigured")
    check("enabled when a repo and a token are set", records.enabled() is True)

    print("\nseveral turns of one intake cost one upload")
    for turn in (1, 2, 3):
        records.remember({"session_id": "abc123", "general_information": {"name": f"turn {turn}"}})
    check("nothing is sent before the flush", CALLS == [], str(CALLS))
    check("one record is pending, not three", len(records._pending) == 1)

    records._flush()
    check("the file is created", path in FILES)
    check("it holds the last turn", '"turn 3"' in FILES[path][1], FILES[path][1][:60])
    check("three turns, one PUT", puts() == [("PUT", path, 201)], str(CALLS))

    print("\na later turn replaces the file")
    CALLS.clear()
    records.remember({"session_id": "abc123", "general_information": {"name": "later"}})
    records._flush()
    check("replaced rather than duplicated", FILES[path][1].count("later") == 1)
    check("no second read - the sha was cached", not gets(), str(CALLS))
    check("the replacement succeeded", ("PUT", path, 200) in CALLS, str(CALLS))

    print("\na stale sha is recovered, not lost")
    CALLS.clear()
    records._blob_sha["abc123"] = "0" * 40        # as if something else wrote it
    records.remember({"session_id": "abc123", "general_information": {"name": "after conflict"}})
    records._flush()
    check("conflict, then a successful retry",
          [call[2] for call in puts()] == [409, 200], str(CALLS))
    check("the record survived the conflict", "after conflict" in FILES[path][1])

    print("\na session not seen before is read once")
    CALLS.clear()
    records.remember({"session_id": "new999", "current_concerns": {"goals": "sleep"}})
    records._flush()
    check("one read, which 404s", gets() == [("GET", "records/new999.json", 404)], str(CALLS))

    print("\na failed upload is kept and retried")
    CALLS.clear()
    reachable = os.environ["CIRA_RECORD_API"]
    os.environ["CIRA_RECORD_API"] = "http://127.0.0.1:1"        # nothing listening
    records.remember({"session_id": "keepme", "current_concerns": {"goals": "retry"}})
    records._flush()
    check("still pending after the failure", "keepme" in records._pending)
    os.environ["CIRA_RECORD_API"] = reachable
    records._flush()
    check("uploaded on the next flush", "records/keepme.json" in FILES)
    check("the queue drains", not records._pending, str(records._pending))

    print("\nthe startup check tells the truth about the repository")
    CALLS.clear()
    records._verify()
    check("a working repository reports reachable", records.reachable() is True)

    Handler.repo_status = 401                      # as an expired token would
    records._verify()
    check("a refused token reports NOT reachable", records.reachable() is False)

    Handler.repo_status = 404                      # as a deleted repo would
    records._verify()
    check("a missing repository reports NOT reachable", records.reachable() is False)

    Handler.repo_status = 200
    records._verify()
    check("it recovers when the repository works again", records.reachable() is True)

    print("\nunconfigured, nothing happens")
    os.environ.pop("CIRA_RECORD_REPO")
    check("not enabled without a repo", records.enabled() is False)
    before = len(CALLS)
    records.remember({"session_id": "ignored", "general_information": {"name": "nobody"}})
    records._flush()
    check("remember() is a no-op", len(CALLS) == before)

    print("\n" + "=" * 66)
    if FAILURES:
        print(f"{len(FAILURES)} CHECK(S) FAILED: " + ", ".join(FAILURES))
        print("=" * 66)
        sys.exit(1)
    print(f"ALL {PASSED} CHECKS PASSED")
    print("=" * 66)


if __name__ == "__main__":
    main()
