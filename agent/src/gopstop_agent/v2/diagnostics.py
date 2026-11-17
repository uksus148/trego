"""Safe stage metadata only; no request values or exception text."""

import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter
from uuid import uuid4


log = logging.getLogger("gopstop_agent.v2")
trace_id: ContextVar[str | None] = ContextVar("v2_trace", default=None)


@contextmanager
def request_trace() -> Iterator[str]:
    value = uuid4().hex
    token = trace_id.set(value)
    try:
        yield value
    finally:
        trace_id.reset(token)


@contextmanager
def stage(name: str) -> Iterator[None]:
    """Stage names are application constants, never user/provider text."""
    started, level, outcome = perf_counter(), logging.INFO, "ok"
    try:
        yield
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    except Exception:
        level, outcome = logging.ERROR, "failed"
        raise
    finally:
        log.log(level, "trace=%s stage=%s outcome=%s elapsed_ms=%.1f",
                trace_id.get(), name, outcome, (perf_counter() - started) * 1000)
