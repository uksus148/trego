"""Correlate internal stages without logging messages, keys or raw session IDs."""

import hashlib
import asyncio
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4

from gopstop_agent.provider_errors import ProviderError

log = logging.getLogger(__name__)
current = ContextVar("chat_trace", default=None)
candidate = ContextVar("chat_candidate", default=None)


@contextmanager
def trace(session_id: str):
    token = current.set((uuid4().hex[:12], hashlib.sha256(session_id.encode()).hexdigest()[:12]))
    try:
        yield current.get()[0]
    finally:
        current.reset(token)


@contextmanager
def stage(name: str):
    started, outcome = time.monotonic(), "ok"
    details = {}
    try:
        yield
    except BaseException as exc:
        outcome = type(exc).__name__
        if isinstance(exc, ProviderError):
            details = exc.diagnostic
        elif isinstance(exc, TimeoutError):
            details = {"reason": "deadline"}
        elif isinstance(exc, asyncio.CancelledError):
            details = {"reason": "cancelled"}
        raise
    finally:
        if current.get() is not None:
            request, session = current.get()
            suffix = " ".join(f"{key}={value}" for key, value in details.items())
            level = logging.WARNING if outcome not in ("ok", "CancelledError") else logging.INFO
            log.log(level, "chat trace=%s session=%s candidate=%s stage=%s elapsed_ms=%.0f outcome=%s %s",
                    request, session, candidate.get(), name, (time.monotonic() - started) * 1000, outcome, suffix)


@contextmanager
def candidate_scope(index: int):
    token = candidate.set(index)
    try:
        yield
    finally:
        candidate.reset(token)


def cache_event(cache: str, result: str):
    if current.get() is not None:
        request, session = current.get()
        log.info("chat trace=%s session=%s candidate=%s cache=%s result=%s",
                 request, session, candidate.get(), cache, result)
