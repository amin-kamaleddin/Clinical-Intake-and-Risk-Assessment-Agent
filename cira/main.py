"""Start the CIRA intake interface.

    python main.py                      # http://127.0.0.1:8000
    CIRA_PORT=8080 python main.py       # a different port
    CIRA_HOST=0.0.0.0 python main.py    # reachable on the local network

The interface is a FastAPI service that serves the page and exposes the agent
behind a small JSON API; see cira/web/server.py.
"""

import os

import uvicorn

from web.server import app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.getenv("CIRA_HOST", "127.0.0.1"),
        port=int(os.getenv("CIRA_PORT", "8000")),
    )
