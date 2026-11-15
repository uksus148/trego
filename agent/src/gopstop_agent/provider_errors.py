"""Allowlisted diagnostic metadata; never retain provider bodies in log fields."""

import httpx
from pydantic import ValidationError


PROVIDERS = {"anthropic", "groq", "exa", "nominatim"}
OPERATIONS = {"select_reply_language", "extract_route_intent", "resolve_place", "write_chat_reply", "assess_availability", "search", "geocode"}
REASONS = {"http_status", "transport", "timeout", "request_schema", "response_json",
           "incomplete_generation", "unexpected_tool", "tool_arguments", "schema_validation",
           "invalid_source_index", "no_usable_sources", "discovery_deadline", "model_refusal", "structured_content"}
CODES = {"tool_use_failed", "rate_limit_exceeded", "insufficient_quota", "invalid_api_key",
         "model_not_found", "model_decommissioned", "context_length_exceeded",
         "invalid_request_error", "authentication_error", "permission_error", "rate_limit_error",
         "not_found_error", "overloaded_error", "api_error"}
FINISHES = {"tool_calls", "stop", "length", "content_filter", "tool_use", "end_turn", "max_tokens", "refusal"}
TIMEOUTS = {"ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout"}
VALIDATION_TYPES = {"missing", "extra_forbidden", "string_type", "string_too_short", "string_too_long",
                    "int_type", "list_type", "model_type", "dict_type", "less_than_equal",
                    "greater_than_equal", "too_long", "value_error", "literal_error", "invalid_target_reference"}
VALIDATION_FIELDS = {"start", "end", "mustSee", "preferences", "descriptiveTargets", "place",
                     "name", "geocodeQuery", "sourceIndex", "tags"}


def allowed(value, choices):
    return value if isinstance(value, str) and value in choices else "unknown"


class ProviderError(Exception):
    """Public message and separate, strictly sanitized diagnostic fields."""

    def __init__(self, message: str, *, provider=None, operation=None, reason=None,
                 status=None, code=None, finish=None, timeout=None, validation: ValidationError | None = None):
        super().__init__(message)
        self.diagnostic = {
            "provider": allowed(provider, PROVIDERS), "operation": allowed(operation, OPERATIONS),
            "reason": allowed(reason, REASONS),
        }
        if type(status) is int and 100 <= status <= 599:
            self.diagnostic["http_status"] = status
        for key, value, choices in (("provider_code", code, CODES), ("finish_reason", finish, FINISHES),
                                    ("timeout_kind", timeout, TIMEOUTS)):
            if value is not None:
                self.diagnostic[key] = allowed(value, choices)
        if validation is not None:
            self.diagnostic["validation_count"] = validation.error_count()
            errors = validation.errors(include_url=False, include_context=False, include_input=False)
            self.diagnostic["validation_types"] = ",".join(
                sorted({allowed(error["type"], VALIDATION_TYPES) for error in errors})[:3])
            self.diagnostic["validation_fields"] = ",".join(sorted({
                allowed(error["loc"][0], VALIDATION_FIELDS) if error["loc"] else "root" for error in errors})[:3])


class ProviderTimeout(ProviderError):
    """A provider or internal discovery deadline elapsed."""


def http_failure(response: httpx.Response, *, provider: str, operation: str) -> ProviderError:
    code = None
    # Parse only a small error envelope. Never extract message/failed_generation.
    if len(response.content) <= 8192:
        try:
            error = response.json().get("error", {})
            if isinstance(error, dict):
                code = error.get("code") or error.get("type")
        except (ValueError, AttributeError):
            pass
    return ProviderError("Provider request is temporarily unavailable.", provider=provider,
                         operation=operation, reason="http_status", status=response.status_code,
                         code=code if code is not None else "unknown")
