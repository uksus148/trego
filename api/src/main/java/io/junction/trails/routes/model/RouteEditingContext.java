package io.junction.trails.routes.model;

import io.junction.trails.places.model.Place;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

public record RouteEditingContext(UUID routeId, Endpoint start, Endpoint end,
                                  List<Place> stops, List<String> preferences) {
    public RouteEditingContext {
        Objects.requireNonNull(routeId, "Saved route ID is required");
        Objects.requireNonNull(start, "Start is required");
        Objects.requireNonNull(end, "End is required");
        stops = List.copyOf(stops);
        preferences = List.copyOf(preferences);
        if (stops.size() > NewRoute.MAX_INTERMEDIATE_STOPS) {
            throw new IllegalArgumentException("Saved route exceeds the supported visit count");
        }
    }

    public record Endpoint(double lat, double lon, Place place) {
        public Endpoint {
            new GeoPoint(lat, lon);
            if (place != null && (lat != place.lat() || lon != place.lon())) {
                throw new IllegalArgumentException("Saved endpoint coordinates differ from their bound place");
            }
        }
    }
}
