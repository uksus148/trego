"""Actual agent factories with strict provider fixtures and real loopback API HTTP."""

import json
import os
from pathlib import Path

import httpx

from trego_agent.config import Settings

# main creates a default app on import; prevent even that unused app from reading .env.
Settings.model_config["env_file"] = None
from trego_agent.main import create_app  # noqa: E402

CORPUS = json.loads((Path(__file__).parents[2] / "docs/contracts/baseline.examples.json").read_text())
CALLS = []


class FixtureTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.local = httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request):
        url = request.url
        if url.scheme == "http" and url.host == "127.0.0.1" and url.port == int(os.environ["E2E_API_PORT"]):
            if not url.path.startswith("/api/"):
                raise AssertionError("Unexpected local API path")
            CALLS.append("api:" + request.method + ":" + url.path)
            return await self.local.handle_async_request(request)
        body = json.loads(request.content) if request.content else {}
        if url.host == "api.groq.com" and url.path == "/openai/v1/chat/completions":
            operation = body["response_format"]["json_schema"]["name"]
            CALLS.append(operation)
            if operation == "select_reply_language":
                result = {"language": "en"}
            elif operation == "extract_route_intent":
                incomplete = CORPUS["incompleteMessage"] in body["messages"][-1]["content"]
                result = {"start": None, "end": None, "mustSee": [], "preferences": []} if incomplete else CORPUS["intent"]
                result = {**result, "descriptiveTargets": []}
            elif operation == "select_explore_area":
                # The fixture corpus contains no popular-places tour requests.
                result = {"area": None}
            elif operation == "resolve_place":
                evidence = json.loads(body["messages"][-1]["content"])
                name = evidence["sources"][0]["title"]
                assert name in [p["name"] for p in CORPUS["places"]]
                result = {"place": {"name": name, "geocodeQuery": name + ", Slovakia", "sourceIndex": 0, "tags": []}}
            else:
                raise AssertionError("Unexpected model operation: " + operation)
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]})
        if url.host == "api.exa.ai" and url.path == "/search":
            prefix = "Find information about this exact place: "
            assert body["query"].startswith(prefix), "Unexpected research query protocol"
            name = body["query"].removeprefix(prefix).split(". Route context:")[0]
            place = next(p for p in CORPUS["places"] if p["name"] == name)
            CALLS.append("exa")
            return httpx.Response(200, json={"results": [{"title": name, "url": place["source"], "text": "Synthetic place in Slovakia"}]})
        if url.host == "nominatim.openstreetmap.org" and url.path == "/search":
            name = url.params["q"].split(",")[0]
            index = next(i for i,p in enumerate(CORPUS["places"]) if p["name"] == name)
            place = CORPUS["places"][index]
            CALLS.append("nominatim")
            return httpx.Response(200, json=[{"osm_type": "node", "osm_id": CORPUS["osmIds"][index],
                                           "display_name": name, "lat": place["lat"], "lon": place["lon"]}])
        raise AssertionError("Blocked unexpected outbound host/path: " + url.host + url.path)

    async def aclose(self):
        await self.local.aclose()


settings = Settings(_env_file=None, chat_enabled=True, llm_provider="groq", groq_api_key="fixture-only",
                    exa_api_key="fixture-only", api_base_url=f"http://127.0.0.1:{os.environ['E2E_API_PORT']}",
                    valkey_url=os.environ["E2E_VALKEY_URL"], cors_origins=[os.environ["E2E_FRONTEND_URL"]])
provider_http = httpx.AsyncClient(transport=FixtureTransport(), trust_env=False)
app = create_app(settings, http_client=provider_http)


@app.get("/__fixture/calls")
def calls():
    # Test-only entrypoint; never imported by production startup.
    return CALLS
