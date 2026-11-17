"""Shared accepted examples, not a new public schema or live-geography assertion."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from trego_agent.api_models import ApiPlace, ApiRoute
from trego_agent.trails_api import TrailsApi, HandoffError


def test_shared_baseline_corpus_and_negative_controls():
    corpus = json.loads((Path(__file__).parents[2] / "docs/contracts/baseline.examples.json").read_text())
    route = ApiRoute.model_validate_json(json.dumps(corpus["route"]))
    places = [ApiPlace.model_validate_json(json.dumps(p)) for p in corpus["places"]]
    stops = [places[i] for i in corpus["stopIndexes"]]
    TrailsApi.check_stops(route, stops)
    with pytest.raises(HandoffError):
        TrailsApi.check_stops(route.model_copy(update={"places": [stops[0], stops[2], stops[1]]}), stops)
    broken = dict(corpus["route"])
    del broken["geojson"]
    with pytest.raises(ValidationError):
        ApiRoute.model_validate_json(json.dumps(broken))
