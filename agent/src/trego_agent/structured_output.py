"""Provider-neutral extraction specification and a conservative strict wire schema."""

from dataclasses import dataclass

from jsonschema import Draft202012Validator


# Each ID was checked against Groq with the exact strict json_schema payload below.
GROQ_STRUCTURED_MODELS = frozenset({"openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.8-27b"})
# Qwen spends ~950 reasoning tokens per call at "low", exhausting a 1000 output-tokens-per-minute
# tier after one request; it extracts the same fields without reasoning.
GROQ_REASONING_EFFORT = {"qwen/qwen3.8-27b": "none"}
# These constraints stay in the application's Pydantic validators. In particular,
# constraining intent list length during generation could silently drop user stops.
LOCAL_CONSTRAINTS = {"minLength", "maxLength", "minItems", "maxItems", "minimum", "maximum",
                     "exclusiveMinimum", "exclusiveMaximum", "pattern", "format", "default", "title"}


def strict_schema(schema: dict) -> dict:
    definitions = schema.get("$defs", {})

    def convert(node, active=()):
        if "$ref" in node:
            ref = node["$ref"]
            if not isinstance(ref, str) or not ref.startswith("#/$defs/") or ref in active:
                raise ValueError("Unsupported schema reference.")
            if set(node) - {"$ref"} - LOCAL_CONSTRAINTS - {"description"}:
                raise ValueError("Unsupported schema reference siblings.")
            return convert(definitions[ref.removeprefix("#/$defs/")], (*active, ref))
        allowed = {"type", "properties", "required", "additionalProperties", "items", "anyOf", "enum", "description"}
        if set(node) - allowed - LOCAL_CONSTRAINTS - {"$defs"}:
            raise ValueError("Unsupported schema keyword.")
        result = {k: v for k, v in node.items() if k in allowed}
        if node.get("type") == "object":
            if node.get("additionalProperties") is not False:
                raise ValueError("Structured objects must be closed.")
            result["properties"] = {k: convert(v, active) for k, v in node["properties"].items()}
            result["required"] = list(result["properties"])
        if "items" in node:
            result["items"] = convert(node["items"], active)
        if "anyOf" in node:
            result["anyOf"] = [convert(v, active) for v in node["anyOf"]]
        return result

    result = convert(schema)
    if result.get("type") != "object":
        raise ValueError("Structured output requires a root object.")
    Draft202012Validator.check_schema(result)
    return result


@dataclass(frozen=True)
class StructuredRequest:
    operation: str
    model: str
    system: str
    messages: list[dict]
    schema: dict
    max_tokens: int

    @classmethod
    def from_tool_request(cls, body: dict):
        """Compatibility boundary for the existing task adapters."""
        tool, = body["tools"]
        if tool["name"] != body["tool_choice"]["name"]:
            raise ValueError("Mismatched extraction operation.")
        return cls(tool["name"], body["model"], body["system"], body["messages"],
                   tool["input_schema"], body["max_tokens"])

    def groq_payload(self) -> dict:
        if self.model not in GROQ_STRUCTURED_MODELS:
            raise ValueError("Selected Groq model does not have a supported strict output adapter.")
        return {
            "model": self.model, "max_completion_tokens": max(2048, self.max_tokens),
            "messages": [{"role": "system", "content": self.system}, *self.messages],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": self.operation, "strict": True, "schema": strict_schema(self.schema),
            }},
            "reasoning_effort": GROQ_REASONING_EFFORT.get(self.model, "low"),
        }
