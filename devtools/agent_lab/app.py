"""Authenticated local UI around the real v2 app; no live adapters or dotenv."""

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from trego_agent.v2.chat import FixtureChatService
from trego_agent.v2.config import AppSettings
from trego_agent.v2.main import create_app as create_core

from .config import APPLICATION, PORT
from .credentials import Vault
from .records import CaptureHandler, Records

Provider = Literal["groq", "anthropic", "exa"]


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    request: dict
    mode: Literal["foundation", "failure", "wait"] = "foundation"
    timeout_seconds: float = Field(default=10, gt=0, le=60)
    inspect: bool = False


class KeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    provider: Provider
    value: SecretStr = Field(min_length=8, max_length=2000)
    remember: bool = False


class DiagnosticService:
    """Test technical failures, never branch on a message or geographic name."""
    def __init__(self, mode):
        self.mode = mode

    async def respond(self, request):
        if self.mode == "failure":
            raise RuntimeError("Deliberate diagnostic failure")
        await asyncio.Event().wait()


class Lab:
    def __init__(self, token, vault):
        self.vault, self.keys, self.saved = vault, {}, set()
        self.vault_error = False
        for provider in ("groq", "anthropic", "exa"):
            try:
                value = vault.read(provider)
                if value:
                    self.keys[provider] = value
                    self.saved.add(provider)
            except OSError:
                self.vault_error = True
        self.records = Records(lambda: [token, *self.keys.values()])
        self.task, self.server = None, None

    @property
    def busy(self):
        return self.task is not None and not self.task.done()

    def idle(self):
        if self.busy:
            raise HTTPException(409, "Finish or cancel the active run first.")

    async def cancel(self):
        if self.busy:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                self.records.runs[-1]["status"] = "cancelled"

    async def execute(self, payload, record):
        started = perf_counter()
        service = FixtureChatService() if payload.mode == "foundation" else DiagnosticService(payload.mode)
        core = create_core(AppSettings(chat_timeout_seconds=payload.timeout_seconds), service)
        if payload.inspect:
            record["request"] = self.records.bounded(payload.request)
        with self.records.capture(record):
            self.records.event(record, {"level": "WARNING", "stage": "lab",
                "message": "Diagnostic mode only. LLM, research, geocoding, Java and storage are not connected."})
            try:
                async with core.router.lifespan_context(core), httpx.AsyncClient(
                    transport=httpx.ASGITransport(core), base_url="http://core.invalid", trust_env=False,
                ) as client:
                    response = await client.post("/api/chat", json=payload.request)
                    record.update(httpStatus=response.status_code, traceId=response.headers.get("X-Trace-Id"),
                                  status="completed" if response.is_success else "failed")
                    if payload.inspect:
                        record["response"] = self.records.bounded(response.json())
            except asyncio.CancelledError:
                record["status"] = "cancelled"
                self.records.event(record, {"stage": "lab", "message": "Run cancelled. No request replay."})
            except Exception:
                record["status"] = "failed"
                self.records.event(record, {"level": "ERROR", "stage": "lab", "message": "Local run failed."})
            finally:
                record["elapsedMs"] = round((perf_counter() - started) * 1000, 1)


def create_app(token: str, vault=None) -> FastAPI:
    if len(token) < 32:
        raise ValueError("A private launch token is required.")
    lab = Lab(token, vault if vault is not None else Vault())

    @asynccontextmanager
    async def lifespan(app):
        logger = logging.getLogger("trego_agent.v2")
        handler, old_level = CaptureHandler(lab.records), logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        try:
            yield
        finally:
            await lab.cancel()
            lab.keys.clear()
            lab.records.runs.clear()
            logger.removeHandler(handler)
            logger.setLevel(old_level)

    app = FastAPI(title="trego. v2 local lab", docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)
    app.state.lab = lab

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, exc):
        return JSONResponse({"detail": "Invalid lab fields. Check the selected options."}, status_code=422)

    @app.middleware("http")
    async def protect(request: Request, call_next):
        host = request.headers.get("host", "")
        origin = request.headers.get("origin")
        if host not in {f"127.0.0.1:{PORT}", f"localhost:{PORT}"} or (
            origin is not None and origin != "http://" + host
        ):
            return JSONResponse({"detail": "Invalid local host or origin."}, status_code=403)
        if request.url.path.startswith("/lab/") and not secrets.compare_digest(
            request.headers.get("x-lab-token", "").encode(), token.encode(),
        ):
            return JSONResponse({"detail": "Open the lab using Start-Agent-Lab.cmd."}, status_code=403)
        if request.method == "POST":
            try:
                size = int(request.headers.get("content-length", "-1"))
            except ValueError:
                size = -1
            if size < 0 or size > 32768:
                return JSONResponse({"detail": "A bounded request body is required."}, status_code=413)
            if len(await request.body()) > 32768:
                return JSONResponse({"detail": "Request body is too large."}, status_code=413)
        try:
            response = await call_next(request)
        except Exception:
            logging.getLogger(__name__).error("Local lab request failed.")
            response = JSONResponse({"detail": "Unexpected lab failure."}, status_code=500)
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer", "Content-Security-Policy":
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"})
        return response

    @app.get("/")
    async def index():
        return HTMLResponse(Path(__file__).with_name("index.html").read_text(encoding="utf-8"))

    @app.get("/assets/{name}")
    async def asset(name: str):
        if name not in {"lab.js", "lab.css"}:
            raise HTTPException(404)
        return Response(Path(__file__).with_name(name).read_text(encoding="utf-8"),
                        media_type="text/javascript" if name.endswith(".js") else "text/css")

    @app.get("/lab/status")
    async def status():
        return {"application": APPLICATION, "busy": lab.busy,
            "keys": {p: {"present": p in lab.keys, "saved": p in lab.saved} for p in ("groq", "anthropic", "exa")},
            "vaultAvailable": bool(lab.vault.api), "vaultError": lab.vault_error,
            "capabilities": [{"id": name, "available": name in {"http", "events"}}
                             for name in ("http", "events", "llm", "research", "geocoding", "java", "sessions")],
            "runs": [{"mode": r["options"]["mode"], **{k: r[k] for k in ("id", "created", "status", "httpStatus", "elapsedMs")}}
                     for r in lab.records.runs]}

    def find_run(run_id):
        record = next((r for r in lab.records.runs if r["id"] == run_id), None)
        if record is None:
            raise HTTPException(404, "Run not found.")
        return record

    @app.get("/lab/runs/{run_id}")
    async def details(run_id: str):
        return find_run(run_id)

    @app.get("/lab/export/{run_id}")
    async def export(run_id: str):
        record = find_run(run_id)
        return JSONResponse(record, headers={"Content-Disposition": f'attachment; filename="trego-run-{record["id"]}.json"'})

    @app.post("/lab/run", status_code=202)
    async def run(payload: RunRequest):
        lab.idle()
        record = lab.records.start(payload.model_dump(exclude={"request"}))
        lab.task = asyncio.create_task(lab.execute(payload, record))
        return {"runId": record["id"]}

    @app.post("/lab/cancel")
    async def cancel():
        await lab.cancel()
        return {"cancelled": True}

    @app.post("/lab/reset")
    async def reset():
        lab.idle()
        lab.records.runs.clear()
        return {"cleared": True}

    @app.post("/lab/keys")
    async def save_key(payload: KeyRequest):
        lab.idle()
        value = payload.value.get_secret_value().strip()
        if len(value) < 8 or any(c.isspace() for c in value):
            raise HTTPException(400, "A key needs at least 8 characters and no whitespace.")
        try:
            if payload.remember:
                lab.vault.write(payload.provider, value)
            else:
                lab.vault.delete(payload.provider)
        except OSError:
            raise HTTPException(503, "Windows key storage is unavailable. No key was changed.") from None
        lab.keys[payload.provider] = value
        lab.saved.add(payload.provider) if payload.remember else lab.saved.discard(payload.provider)
        return {"saved": payload.remember}

    @app.delete("/lab/keys/{provider}")
    async def delete_key(provider: Provider):
        lab.idle()
        try:
            lab.vault.delete(provider)
        except OSError:
            raise HTTPException(503, "Windows key storage could not delete the key.") from None
        lab.keys.pop(provider, None)
        lab.saved.discard(provider)
        return {"deleted": True}

    @app.post("/lab/stop")
    async def stop():
        await lab.cancel()
        if lab.server is not None:
            lab.server.should_exit = True
        return {"stopping": True}

    return app
