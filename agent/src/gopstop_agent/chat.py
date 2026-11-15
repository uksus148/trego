"""Compose existing discovery/handoff and language-aware replies."""

import httpx
from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError

from gopstop_agent.api_models import ApiPlace
from gopstop_agent.config import Settings
from gopstop_agent.diagnostics import stage
from gopstop_agent.discovery import PlaceDiscovery, create_discovery
from gopstop_agent.handoff import RouteHandoff, create_handoff
from gopstop_agent.intent import IntentClarificationRequired, Message
from gopstop_agent.llm import create_tool_model
from gopstop_agent.localized_replies import FactualReplyWriter, LanguageSelector, LANGUAGE_QUESTION
from gopstop_agent.trails_api import HandoffError, NoHikingRoute, WaypointNotRoutable


class ChatResponse(BaseModel):
    reply: str
    places: list[ApiPlace]
    routeId: str | None = None


class ChatService:
    def __init__(self, discovery: PlaceDiscovery, handoff: RouteHandoff,
                 replies, language_selector: LanguageSelector | None = None) -> None:
        self._discovery, self._handoff, self._replies = discovery, handoff, replies
        self._language_selector = language_selector

    async def respond(self, message: str, history: list[Message]) -> ChatResponse:
        language = "en"
        if self._language_selector is not None:
            with stage("language"):
                language = await self._language_selector.select(message, history)
            if language == "unknown":
                return ChatResponse(reply=LANGUAGE_QUESTION, places=[])
        places, route_id = [], None
        try:
            with stage("discovery"):
                finding = await self._discovery.discover(message, history)
        except IntentClarificationRequired as exc:
            outcome, facts = "clarification", {"intentLimits": True}
        except RedisError as exc:
            raise HandoffError("Place research cache is temporarily unavailable.", 503) from exc
        else:
            if not finding.ready_for_handoff:
                outcome, facts = "clarification", {
                    "missingEndpoints": finding.missing_endpoints, "unresolvedPlaces": finding.unresolved,
                }
            else:
                try:
                    with stage("handoff"):
                        saved = await self._handoff.persist(finding)
                except NoHikingRoute:
                    outcome, facts = "no_route", {"question": "Please choose different endpoints or stops."}
                except WaypointNotRoutable:
                    outcome, facts = "waypoint_not_routable", {
                        "reason": "A waypoint could not be matched to the available hiking network within the search radius.",
                        "question": "Please verify the coordinates or choose a different endpoint or stop.",
                    }
                else:
                    outcome, facts = "ready", {
                        "visits": saved.visits or [place.name for place in saved.places],
                        "intermediateStops": [place.name for place in saved.route.places],
                        "distanceKm": saved.route.distanceKm, "ascentM": saved.route.ascentM,
                        "durationMin": saved.route.durationMin,
                    }
                    places, route_id = saved.places, saved.route.id
        with stage("reply"):
            options = {"language": language} if self._language_selector is not None else {}
            reply = await self._replies.write(message, history, outcome, facts, **options)
        return ChatResponse(reply=reply, places=places, routeId=route_id)


def create_chat(client: httpx.AsyncClient, cache: Redis, settings: Settings) -> ChatService:
    model = create_tool_model(client, settings)
    return ChatService(create_discovery(client, cache, settings, model), create_handoff(client, settings),
                       FactualReplyWriter(), LanguageSelector(model, settings.llm_model))
