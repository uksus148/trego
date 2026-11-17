"""Explicit discovery diagnostic: no Java, route or chat-session capability."""

import argparse
import asyncio
import json
import logging
import time
from uuid import uuid4

import httpx
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import RedisError

from trego_agent.config import Settings
from trego_agent.diagnostics import stage, trace
from trego_agent.discovery import create_discovery
from trego_agent.intent import IntentClarificationRequired, ProviderError
from trego_agent.valkey import from_url


async def run_probe(settings, client, cache, message: str, *, cold: bool = False, shared_research: bool = False,
                    include_identity: bool = False) -> dict:
    settings.require_chat_configuration()
    if not message.strip() or len(message) > 4000:
        raise ValueError("Probe message must contain 1-4000 characters.")
    if cold and shared_research:
        raise ValueError("Shared research requires the ordinary shared geocoding profile.")
    namespace = None if shared_research else f"gopstop:probe-discovery:{uuid4().hex}"
    report = {"status": "failed", "provider": settings.llm_provider,
              "modelProfile": settings.llm_model if settings.llm_provider == "groq" else "anthropic", "geocodingCache": "isolated" if cold else "shared",
              "researchCache": "shared" if shared_research else "isolated", "findings": []}
    started = time.monotonic()
    with trace("discovery-probe") as trace_id:
        report["traceId"] = trace_id
        try:
            with stage("discovery"):
                finding = await create_discovery(client, cache, settings, diagnostic_namespace=namespace,
                                                 cold_geocoding=cold).discover(message, [])
            report["missingEndpoints"] = finding.missing_endpoints
            if include_identity:
                report["intentTargets"] = finding.intent.model_dump(include={"start", "end", "mustSee", "descriptiveTargets"})
            unique = {}
            for place in [finding.start, *finding.stops, finding.end]:
                if place is not None:
                    unique.setdefault(place.description, place)
            for index, place in enumerate(unique.values()):
                selection = place.selection
                item = {"candidate": index, "reason": place.reason,
                        "sourceCount": len(place.sources), **(selection.model_dump(exclude={"location", "reason"}) if selection else {})}
                if include_identity:
                    item["identity"] = {"requestedTarget": place.description,
                        "resolution": place.resolution.model_dump() if place.resolution else None,
                        "selectedOsm": {"osmType": place.place.location.osm_type, "osmId": place.place.location.osm_id}
                            if place.place else None}
                report["findings"].append(item)
            report["status"] = "ready" if finding.ready_for_handoff else "needs_clarification"
        except IntentClarificationRequired:
            report.update(status="needs_clarification", reason="intent_limits")
        except ProviderError as exc:
            report["error"] = exc.diagnostic
        except RedisError:
            report["error"] = {"reason": "storage_unavailable"}
        finally:
            try:
                async with asyncio.timeout(2):
                    if namespace is not None:
                        async for key in cache.scan_iter(match=namespace + ":*"):
                            await cache.delete(key)
            except (RedisError, TimeoutError):
                report["cleanupFailed"] = True
    report["elapsedMs"] = round((time.monotonic() - started) * 1000)
    return report


async def _main(message, cold, shared_research=False, include_identity=False):
    settings = Settings()
    async with httpx.AsyncClient(follow_redirects=False) as client, from_url(
        str(settings.valkey_url), decode_responses=True,
        socket_connect_timeout=settings.valkey_connect_timeout_seconds,
        socket_timeout=settings.valkey_socket_timeout_seconds,
        health_check_interval=settings.valkey_health_check_interval_seconds,
        socket_keepalive=True, retry=Retry(NoBackoff(), 0),
    ) as cache:
        return await run_probe(settings, client, cache, message, cold=cold, shared_research=shared_research,
                               include_identity=include_identity)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--message", required=True)
    parser.add_argument("--cold", action="store_true", help="Use isolated Nominatim candidate cache; retain the shared rate gate.")
    parser.add_argument("--shared-research", action="store_true", help="Use ordinary chat caches including resolution; do not clean shared keys.")
    parser.add_argument("--include-identity", action="store_true", help="Include private intent targets and resolution names/queries in local JSON only.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("trego_agent.diagnostics").setLevel(logging.INFO)
    try:
        report = asyncio.run(_main(args.message, args.cold, args.shared_research, args.include_identity))
    except ValueError:
        report = {"status": "failed", "error": {"reason": "invalid_configuration"}}
    print(json.dumps(report))
    raise SystemExit(1 if report["status"] == "failed" or report.get("cleanupFailed") else 0)


if __name__ == "__main__":
    main()
