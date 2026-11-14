"""Explicit live Exa -> resolution probe, with no cache, Java or session writes."""

import argparse
import asyncio
import json
import logging
import time

import httpx

from gopstop_agent.config import Settings
from gopstop_agent.diagnostics import stage, trace
from gopstop_agent.exa import ExaSearch
from gopstop_agent.llm import ProviderError, create_tool_model
from gopstop_agent.resolver import ClaudePlaceResolver


async def run_probe(settings: Settings, client: httpx.AsyncClient, query: str) -> dict:
    settings.require_chat_configuration()
    if not query.strip() or len(query) > 4000:
        raise ValueError("Probe query must contain 1-4000 characters.")
    started = time.monotonic()
    report = {"status": "failed", "sourceCount": 0}
    with trace("resolution-probe") as trace_id:
        report["traceId"] = trace_id
        try:
            async with asyncio.timeout(settings.discovery_timeout_seconds):
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
        except ProviderError as exc:
            report["error"] = exc.diagnostic
        except TimeoutError:
            report["error"] = {"reason": "discovery_deadline"}
    report["elapsedMs"] = round((time.monotonic() - started) * 1000)
    return report


async def _main(query: str) -> dict:
    settings = Settings()
    async with httpx.AsyncClient(timeout=settings.provider_timeout_seconds, follow_redirects=False) as client:
        return await run_probe(settings, client, query)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="Full place research query including route context.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("gopstop_agent.diagnostics").setLevel(logging.INFO)
    try:
        report = asyncio.run(_main(args.query))
    except ValueError:
        report = {"status": "failed", "stage": "configuration", "error": {"reason": "invalid_configuration"}}
    print(json.dumps(report))
    raise SystemExit(1 if report["status"] == "failed" else 0)


if __name__ == "__main__":
    main()
