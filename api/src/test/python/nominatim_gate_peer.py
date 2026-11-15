"""Fixture-only peer for the Java/agent gate interoperability test; never calls public providers."""

import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff

from gopstop_agent.config import Settings
from gopstop_agent.geocoding import NominatimGeocoder


async def run(args):
    async with Redis.from_url(args.redis_url, decode_responses=True,
                              socket_timeout=2, retry=Retry(NoBackoff(), 0)) as cache:
        async with httpx.AsyncClient(trust_env=False, timeout=2) as events:
            async def provider(request):
                (await events.post(args.events + "/python-start")).raise_for_status()
                await asyncio.sleep(0.4)
                (await events.post(args.events + "/python-end")).raise_for_status()
                return httpx.Response(200, json=[{
                    "lat": "49", "lon": "20", "osm_type": "node", "osm_id": 42,
                    "display_name": "Fixture", "name": "Fixture", "type": "city", "category": "place",
                }])

            async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
                # Evaluate actual Settings -> geocoder, including Pydantic normalization.
                for vector in json.loads(Path(args.vectors).read_text())["accepted"]:
                    settings = Settings(_env_file=None, nominatim_base_url=vector["configured"])
                    peer = NominatimGeocoder(client, cache, "trego-fixture/1.0", str(settings.nominatim_base_url))
                    assert peer._base_url == vector["base"]
                    assert peer._gate == vector["key"]
                settings = Settings(_env_file=None, nominatim_base_url=args.url)
                peer = NominatimGeocoder(client, cache, "trego-fixture/1.0", str(settings.nominatim_base_url))
                print("READY", flush=True)
                started = time.monotonic()
                while not Path(args.go).exists():
                    if time.monotonic() - started > 10:
                        raise TimeoutError("Java fixture did not release the peer")
                    await asyncio.sleep(0.01)
                result = await peer.geocode("Fixture " + args.query, name="Fixture", tags=["city"])
                assert result and result.osm_id == 42


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("redis-url", "events", "url", "vectors", "go", "query"):
        parser.add_argument("--" + name, required=True)
    asyncio.run(run(parser.parse_args()))
