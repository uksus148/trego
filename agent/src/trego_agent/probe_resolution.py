"""Explicit live intent or Exa -> resolution probe; no cache, Java or session writes."""

import argparse
import asyncio
import json
import logging
import time

import httpx

from trego_agent.config import Settings
from trego_agent.diagnostics import stage, trace
from trego_agent.exa import ExaSearch
from trego_agent.intent import ClaudeIntentExtractor, IntentClarificationRequired
from trego_agent.llm import ProviderError, create_tool_model
from trego_agent.resolver import ClaudePlaceResolver


async def run_probe(settings: Settings, client: httpx.AsyncClient, query: str, *, intent_only: bool = False) -> dict:
    settings.require_chat_configuration()
    if not query.strip() or len(query) > 4000:
        raise ValueError("Probe query must contain 1-4000 characters.")
    started = time.monotonic()
    report = {"status": "failed", "sourceCount": 0}
    with trace("resolution-probe") as trace_id:
        report["traceId"] = trace_id
        try:
            async with asyncio.timeout(settings.discovery_timeout_seconds):
                if intent_only:
                    report["stage"] = "intent"
                    extractor = ClaudeIntentExtractor(client, settings.llm_key.get_secret_value(), settings.llm_model,
                                                       tool_model=create_tool_model(client, settings))
                    with stage("intent"):
                        intent = await extractor.extract(query, [])
                    missing = [name for name in ("start", "end") if getattr(intent, name) is None]
                    report.update(status="needs_clarification" if missing else "complete", missingEndpoints=missing,
                                  stopCount=len(intent.mustSee), preferenceCount=len(intent.preferences))
                else:
                    report["stage"] = "research"
                    with stage("research"):
                        sources = await ExaSearch(client, None, settings.exa_api_key.get_secret_value(),
                                                 settings.provider_timeout_seconds).search(query, use_cache=False)
                    report["sourceCount"] = len(sources)
                    report["stage"] = "resolution"
                    resolver = ClaudePlaceResolver(client, settings.llm_key.get_secret_value(), settings.llm_model,
                                                   tool_model=create_tool_model(client, settings))
                    with stage("resolution"):
                        place = await resolver.resolve(query, sources)
                    report["status"] = "resolved" if place is not None else "unresolved"
        except IntentClarificationRequired:
            report.update(status="needs_clarification", reason="intent_limits")
        except ProviderError as exc:
            report["error"] = exc.diagnostic
        except TimeoutError:
            report["error"] = {"reason": "discovery_deadline"}
    report["elapsedMs"] = round((time.monotonic() - started) * 1000)
    return report


async def _main(query: str, intent_only: bool = False) -> dict:
    settings = Settings()
    async with httpx.AsyncClient(timeout=settings.provider_timeout_seconds, follow_redirects=False) as client:
        return await run_probe(settings, client, query, intent_only=intent_only)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="Full place research query including route context.")
    parser.add_argument("--intent-only", action="store_true", help="Interpret --query as a user message; call only the model.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("trego_agent.diagnostics").setLevel(logging.INFO)
    try:
        report = asyncio.run(_main(args.query, args.intent_only))
    except ValueError:
        report = {"status": "failed", "stage": "configuration", "error": {"reason": "invalid_configuration"}}
    print(json.dumps(report))
    raise SystemExit(1 if report["status"] == "failed" else 0)


if __name__ == "__main__":
    main()
