package io.junction.trails.routes.web;

import com.fasterxml.jackson.annotation.JsonAnySetter;
import com.fasterxml.jackson.databind.JsonNode;
import io.junction.trails.routes.model.GeoPoint;
import io.junction.trails.routes.model.NewRoute;
import io.junction.trails.routes.model.RouteCreation;
import java.util.List;
import java.util.UUID;

record CreateRouteRequest(Point start, Point end, List<UUID> placeIds, List<String> preferences,
                          JsonNode startPlaceId, JsonNode endPlaceId) {
    RouteCreation toCommand() {
        if (start == null || end == null) {
            throw NewRoute.invalid("start and end are required");
        }
        return new RouteCreation(new NewRoute(start.toPoint(), end.toPoint(), placeIds, preferences),
                RouteRequestIds.optional(startPlaceId), RouteRequestIds.optional(endPlaceId));
    }

    @JsonAnySetter
    void unknownField(String field, JsonNode value) {
        throw NewRoute.invalid("Unknown route request field");
    }

    record Point(Double lat, Double lon) {
        @JsonAnySetter
        void unknownField(String field, JsonNode value) {
            throw NewRoute.invalid("Unknown route endpoint field");
        }

        GeoPoint toPoint() {
            if (lat == null || lon == null) {
                throw NewRoute.invalid("lat and lon are required for each endpoint");
            }
            try {
                return new GeoPoint(lat, lon);
            } catch (IllegalArgumentException exception) {
                throw NewRoute.invalid(exception.getMessage());
            }
        }
    }
}
