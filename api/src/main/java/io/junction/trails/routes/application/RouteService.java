package io.junction.trails.routes.application;

import io.junction.trails.routes.model.GeoPoint;
import io.junction.trails.routes.model.Route;
import io.junction.trails.routes.model.RouteCreation;
import io.junction.trails.routes.model.RouteEditingContext;
import io.junction.trails.routes.model.RoutingQuery;
import io.junction.trails.routes.persistence.RoutePersistence;
import java.util.ArrayList;
import java.util.UUID;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class RouteService {
    private final RoutingGateway routing;
    private final RoutePersistence persistence;

    public Route create(RouteCreation creation) {
        var request = creation.routingRequest();
        var stops = persistence.resolveInputs(creation);
        var waypoints = new ArrayList<GeoPoint>();
        waypoints.add(request.start());
        stops.forEach(place -> waypoints.add(new GeoPoint(place.lat(), place.lon())));
        waypoints.add(request.end());
        var track = routing.route(new RoutingQuery(request, waypoints));
        return persistence.save(creation, track);
    }

    public Route get(UUID id) {
        return persistence.get(id);
    }

    public RouteEditingContext editingContext(UUID id) {
        return persistence.editingContext(id);
    }
}
