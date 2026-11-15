package io.junction.trails.routes.model;

import java.util.Objects;
import java.util.UUID;

/** Endpoint identities describe saved places, not additional routing waypoints. */
public record RouteCreation(NewRoute routingRequest, UUID startPlaceId, UUID endPlaceId) {
    public RouteCreation {
        Objects.requireNonNull(routingRequest, "Routing input is required");
    }
}
