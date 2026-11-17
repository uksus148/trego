"""Prepare the frozen local environment and open the authenticated v2 lab."""

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from secrets import token_urlsafe

from devtools.agent_lab.config import APPLICATION, PORT, ROOT, RUNTIME, TOKEN_ENV, URL
from devtools.agent_lab.credentials import Vault

PYTHON = ROOT / "agent/.venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def status(token):
    request = urllib.request.Request(URL + "/lab/status", headers={"X-Lab-Token": token})
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=1) as response:
            return json.load(response).get("application") == APPLICATION
    except (OSError, ValueError):
        return False


def prepare_environment():
    stamp = hashlib.sha256((ROOT / "agent/uv.lock").read_bytes() + (ROOT / "agent/pyproject.toml").read_bytes()).hexdigest()
    marker = RUNTIME / "dependencies.sha256"
    if PYTHON.exists() and marker.exists() and marker.read_text() == stamp:
        return
    print("Preparing locked dependencies for the local lab...", flush=True)
    uv = shutil.which("uv")
    if not uv:
        bootstrap = ROOT / ".lab-bootstrap"
        bootstrap_python = bootstrap / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        uv_path = bootstrap / ("Scripts/uv.exe" if os.name == "nt" else "bin/uv")
        if not bootstrap_python.exists():
            subprocess.run([sys.executable, "-m", "venv", str(bootstrap)], check=True)
        if not uv_path.exists():
            subprocess.run([str(bootstrap_python), "-m", "pip", "install", "uv==0.13.8"], check=True)
        uv = str(uv_path)
    env = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(ROOT / "agent/.venv")}
    env.pop("VIRTUAL_ENV", None)
    subprocess.run([uv, "sync", "--project", str(ROOT / "agent"), "--frozen", "--extra", "test", "--python", "3.12"],
                   check=True, env=env)
    marker.write_text(stamp)


def main():
    os.chdir(ROOT)
    RUNTIME.mkdir(exist_ok=True)
    vault = Vault()
    try:
        existing = vault.read("launcher")
    except OSError:
        existing = None
    if existing and status(existing):
        webbrowser.open(URL + "/#" + existing)
        print("Reopened the running v2 lab.")
        return
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", PORT)) == 0:
            raise RuntimeError(f"Port {PORT} is occupied. Use the existing tab; no process was stopped.")
    prepare_environment()
    token = token_urlsafe(32)
    try:
        vault.write("launcher", token)
    except OSError:
        print("Windows storage unavailable. Keep the opened tab; reopening requires restarting this lab.")
    process, ready = None, False
    try:
        env = {**os.environ, TOKEN_ENV: token}
        env.pop("PYTHONPATH", None)
        with (RUNTIME / "server.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([str(PYTHON), "-m", "devtools.agent_lab"], cwd=ROOT, env=env,
                stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        for _ in range(120):
            if process.poll() is not None:
                break
            if status(token):
                ready = True
                webbrowser.open(URL + "/#" + token)
                print("New Agent Lab is ready. Stop it using the page's Stop lab button.")
                return
            time.sleep(0.25)
        raise RuntimeError("Lab did not start. See .lab/server.log.")
    finally:
        if not ready:
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            try:
                if vault.read("launcher") == token:
                    vault.delete("launcher")
            except OSError:
                pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Never print subprocess arguments, environment or raw provider/credential errors.
        print("Lab launch failed. Check port 8012, Python and .lab/server.log.", file=sys.stderr)
        raise SystemExit(1)
