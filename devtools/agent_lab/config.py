"""One location for local launch paths and identity."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PORT = 8012
URL = f"http://127.0.0.1:{PORT}"
APPLICATION = "trego-v2-lab"
TOKEN_ENV = "TREGO_LAB_TOKEN"
RUNTIME = ROOT / ".lab"
