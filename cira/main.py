"""Start the CIRA intake interface.

    python cira/main.py                      # http://127.0.0.1:8000
    CIRA_PORT=8080 python cira/main.py       # a different port
    CIRA_HOST=0.0.0.0 python cira/main.py    # reachable beyond this machine

The interface is a FastAPI service that serves the page and exposes the agent
behind a small JSON API; see cira/web/server.py.

Records are written relative to the working directory, so start the server
where those records should land.
"""

import os

import uvicorn

from web.server import app


def _port() -> int:
    """The port to bind.

    PORT is what most hosts inject, so it wins; CIRA_PORT is for running it by
    hand. Reading only one of the two is how a deployment ends up listening on
    a port nothing is routed to.
    """
    return int(os.getenv("PORT") or os.getenv("CIRA_PORT") or 8000)


def _host() -> str:
    """The address to bind.

    Loopback by default, because the service has no authentication of its own.
    A host that routes traffic to a container needs 0.0.0.0, which is why the
    container image sets it explicitly rather than leaving it to chance.
    """
    return os.getenv("CIRA_HOST", "127.0.0.1")


if __name__ == "__main__":
    uvicorn.run(app, host=_host(), port=_port())
