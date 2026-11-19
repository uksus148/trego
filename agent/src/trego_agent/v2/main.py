"""Compose the new HTTP boundary with an explicitly supplied chat implementation."""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from trego_agent.provider_errors import ProviderError, ProviderTimeout
from trego_agent.v2.chat import ChatService, FixtureChatService
from trego_agent.v2.config import AppSettings
from trego_agent.v2.diagnostics import log, request_trace, stage, trace_id
from trego_agent.v2.models import ChatRequest, ChatResponse


class ChatDeadlineExceeded(Exception):
    """The local deadline for this request expired."""


def create_app(settings: AppSettings, service: ChatService) -> FastAPI:
    """The caller owns supplied dependencies; this factory opens no connections."""
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        log.info("event=started")
        try:
            yield
        finally:
            log.info("event=stopped")

    app = FastAPI(title="trego. Agent v2 (development)", lifespan=lifespan)

    @app.middleware("http")
    async def traced_request(
        request: Request, call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        with request_trace() as current_trace:
            started = perf_counter()
            try:
                response = await call_next(request)
            except asyncio.CancelledError:
                log.info("trace=%s stage=http outcome=cancelled", current_trace)
                raise
            except Exception:
                # Catch at the HTTP boundary: server tracebacks could expose payloads.
                response = JSONResponse(status_code=500, content={"detail": "Unexpected agent failure."})
            level = logging.ERROR if response.status_code >= 500 else (
                logging.WARNING if response.status_code >= 400 else logging.INFO
            )
            log.log(level, "trace=%s stage=http status=%d elapsed_ms=%.1f",
                    current_trace, response.status_code, (perf_counter() - started) * 1000)
            response.headers["X-Trace-Id"] = current_trace
            return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Default errors may echo the entire body or private unknown-field names.
        log.warning("trace=%s stage=validation outcome=invalid_request", trace_id.get())
        return JSONResponse(status_code=422, content={
            "detail": "Expected nonblank sessionId (1-128) and message (1-4000), with no extra fields.",
        })

    @app.exception_handler(ChatDeadlineExceeded)
    async def deadline(request: Request, exc: ChatDeadlineExceeded) -> JSONResponse:
        return JSONResponse(status_code=504, content={"detail": "Chat exceeded its time limit."})

    @app.exception_handler(ProviderError)
    async def provider_failure(request: Request, exc: ProviderError) -> JSONResponse:
        log.error("trace=%s stage=provider outcome=failed diagnostic=%s", trace_id.get(), exc.diagnostic)
        if isinstance(exc, ProviderTimeout):
            return JSONResponse(status_code=504, content={"detail": "Model request timed out."})
        return JSONResponse(status_code=502, content={"detail": "Model request failed."})

    @app.post("/api/chat", response_model=ChatResponse, response_model_exclude_none=True)
    async def chat(payload: ChatRequest) -> ChatResponse:
        with stage("chat"):
            timeout = asyncio.timeout(settings.chat_timeout_seconds)
            try:
                async with timeout:
                    result = await service.respond(payload)
                    response = ChatResponse.model_validate(result)
            except TimeoutError:
                if timeout.expired():
                    raise ChatDeadlineExceeded() from None
                raise
            if timeout.expired():
                raise ChatDeadlineExceeded()
            return response

    return app


def create_fixture_app() -> FastAPI:
    """Uvicorn --factory entrypoint for the explicitly labelled, network-free fixture."""
    return create_app(AppSettings(), FixtureChatService())
