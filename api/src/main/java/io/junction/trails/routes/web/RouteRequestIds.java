package io.junction.trails.routes.web;

import com.fasterxml.jackson.databind.JsonNode;
import io.junction.trails.routes.model.NewRoute;
import java.util.UUID;

/** Strict parsing at the HTTP boundary, without changing legacy UUID coercion globally. */
final class RouteRequestIds {
    private RouteRequestIds() { }

    static UUID required(String value) {
        if (value != null) {
            try {
                UUID id = UUID.fromString(value);
                if (id.toString().equalsIgnoreCase(value)) { return id; }
            } catch (IllegalArgumentException ignored) {
                // Java accepts abbreviated UUID groups; the HTTP contract requires the full form.
            }
        }
        throw NewRoute.invalid("Route and endpoint place IDs must be UUID strings");
    }

    static UUID optional(JsonNode value) {
        if (value == null || value.isNull()) { return null; }
        // Default UUID coercion accepts an empty string as null; this contract does not.
        if (value.isTextual()) { return required(value.textValue()); }
        throw NewRoute.invalid("Endpoint place IDs must be UUID strings or null");
    }
}
