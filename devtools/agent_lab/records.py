"""Bounded, redacted records; detailed payloads never enter production logs."""

import json
import logging
import math
import re
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import uuid4

ACTIVE = ContextVar("lab_capture", default=None)
PRIVATE_FIELDS = {"authorization", "apikey", "password", "secret", "secretkey", "cookie",
                  "setcookie", "token", "accesstoken", "refreshtoken", "credential",
                  "credentials", "reasoning", "reasoningcontent"}


class Records:
    def __init__(self, secrets):
        self.secrets = secrets
        self.runs = deque(maxlen=20)

    def clean(self, value, depth=0):
        if depth > 6:
            return "[TRUNCATED: depth]"
        if isinstance(value, dict):
            result = {}
            for key, item in list(value.items())[:64]:
                name = str(key)
                normalized = name.lower().replace("_", "").replace("-", "")
                private = any(normalized.endswith(field) for field in PRIVATE_FIELDS)
                cleaned_name = self.clean(name, depth + 1)
                if not isinstance(cleaned_name, str):
                    cleaned_name = json.dumps(cleaned_name)
                result[cleaned_name] = "[REDACTED]" if private else self.clean(item, depth + 1)
            if len(value) > 64:
                result["[TRUNCATED: fields]"] = True
            return result
        if isinstance(value, (list, tuple)):
            return [self.clean(v, depth + 1) for v in value[:64]] + (
                ["[TRUNCATED: items]"] if len(value) > 64 else []
            )
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, (dict, list)):
                    return self.clean(parsed, depth + 1)
            except (ValueError, RecursionError):
                pass
            for secret in self.secrets():
                if secret:
                    value = value.replace(secret, "[REDACTED]")
            value = re.sub(r"(?i)Bearer\s+[A-Za-z0-9._~-]+", "Bearer [REDACTED]", value)
            value = re.sub(r"\b(?:gsk_|sk-ant-|sk-)[A-Za-z0-9_-]{8,}", "[REDACTED]", value)
            return value if len(value) <= 4096 else value[:4096] + " [TRUNCATED]"
        if isinstance(value, float) and not math.isfinite(value):
            return "[NON-FINITE]"
        return value if isinstance(value, (int, float, bool, type(None))) else "[UNSUPPORTED]"

    def bounded(self, value, limit=16384):
        cleaned = self.clean(value)
        encoded = json.dumps(cleaned, ensure_ascii=False)
        if len(encoded.encode()) > limit:
            return {"truncated": True, "preview": encoded.encode()[:limit // 2].decode(errors="ignore")}
        return cleaned

    def start(self, options):
        record = {"id": uuid4().hex, "created": datetime.now(timezone.utc).isoformat(),
                  "status": "running", "options": self.clean(options), "httpStatus": None,
                  "traceId": None, "request": None, "response": None, "events": [],
                  "elapsedMs": None, "truncated": False}
        self.runs.append(record)
        return record

    def event(self, record, event):
        if len(record["events"]) >= 127:
            if not record["truncated"]:
                record["events"].append({"level": "WARNING", "message": "Event limit reached; capture truncated."})
                record["truncated"] = True
            return
        item = {"level": "INFO", **self.bounded(event, 8192)}
        item["time"] = datetime.now(timezone.utc).isoformat()
        record["events"].append(item)

    @contextmanager
    def capture(self, record):
        token = ACTIVE.set((self, record))
        try:
            yield
        finally:
            ACTIVE.reset(token)


class CaptureHandler(logging.Handler):
    def __init__(self, records):
        super().__init__()
        self.records = records

    def emit(self, record):
        active = ACTIVE.get()
        if active is None or active[0] is not self.records:
            return
        message = record.getMessage()
        stage = re.search(r"\bstage=([a-z_]+)", message)
        self.records.event(active[1], {"level": record.levelname,
            "stage": stage.group(1) if stage else "core", "message": message})
