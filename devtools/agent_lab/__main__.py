"""Run the local server; no production startup or dotenv import."""

import logging
import os

import uvicorn

from .app import create_app
from .config import PORT, TOKEN_ENV
from .credentials import Vault


def main():
    token = os.environ.pop(TOKEN_ENV, None)
    if not token:
        raise SystemExit("Use Start-Agent-Lab.cmd to open a private lab session.")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    app = create_app(token)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, access_log=False))
    app.state.lab.server = server
    try:
        server.run()
    finally:
        vault = Vault()
        try:
            if vault.read("launcher") == token:
                vault.delete("launcher")
        except OSError:
            pass


if __name__ == "__main__":
    main()
