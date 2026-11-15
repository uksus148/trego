package io.junction.trails.routes.persistence;

import io.junction.trails.places.application.PlaceMapper;
import io.junction.trails.places.model.Place;
import io.junction.trails.places.persistence.PlaceEntity;
import io.junction.trails.places.persistence.PlaceRepository;
import io.junction.trails.routes.model.GeoPoint;
import io.junction.trails.routes.model.NewRoute;
import io.junction.trails.routes.model.Route;
import io.junction.trails.routes.model.RouteCreation;
import io.junction.trails.routes.model.RouteEditingContext;
import io.junction.trails.routes.model.RouteException;
import io.junction.trails.routes.model.RouteTrack;
import java.util.List;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.UUID;
import java.util.function.Function;
import java.util.stream.Collectors;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class RoutePersistence {
    private final RouteRepository routes;
    private final PlaceRepository places;

    public List<Place> resolveInputs(RouteCreation creation) {
        return resolvePlaces(creation).stops().stream().map(PlaceMapper::toPlace).toList();
    }

    @Transactional
    public Route save(RouteCreation creation, RouteTrack track) {
        var resolved = resolvePlaces(creation);
        return toRoute(routes.save(new RouteEntity(creation, track, resolved.stops(), resolved.start(), resolved.end())));
    }

    public Route get(UUID id) {
        return toRoute(findRoute(id));
    }

    public RouteEditingContext editingContext(UUID id) {
        var entity = findRoute(id);
        return new RouteEditingContext(entity.getId(), endpoint(entity.getStart(), entity.getStartPlace()),
                endpoint(entity.getEnd(), entity.getEndPlace()),
                entity.getPlaces().stream().map(PlaceMapper::toPlace).toList(), entity.getPreferences());
    }

    private RouteEntity findRoute(UUID id) {
        return routes.findById(id).orElseThrow(() -> new RouteException(
                RouteException.Reason.ROUTE_NOT_FOUND, "The saved route does not exist."));
    }

    private ResolvedPlaces resolvePlaces(RouteCreation creation) {
        var request = creation.routingRequest();
        var ids = new LinkedHashSet<>(request.placeIds());
        if (creation.startPlaceId() != null) { ids.add(creation.startPlaceId()); }
        if (creation.endPlaceId() != null) { ids.add(creation.endPlaceId()); }
        Map<UUID, PlaceEntity> byId = places.findAllById(ids).stream()
                .collect(Collectors.toMap(PlaceEntity::getId, Function.identity()));
        if (byId.size() != ids.size()) {
            throw new RouteException(RouteException.Reason.UNKNOWN_PLACE, "A referenced place does not exist.");
        }
        var start = boundPlace(creation.startPlaceId(), request.start(), byId);
        var end = boundPlace(creation.endPlaceId(), request.end(), byId);
        return new ResolvedPlaces(request.placeIds().stream().map(byId::get).toList(), start, end);
    }

    private static PlaceEntity boundPlace(UUID id, GeoPoint point, Map<UUID, PlaceEntity> byId) {
        if (id == null) { return null; }
        var place = byId.get(id);
        if (point.lat() != place.getLat() || point.lon() != place.getLon()) {
            throw NewRoute.invalid("Endpoint coordinates must match the referenced place.");
        }
        return place;
    }

    private static RouteEditingContext.Endpoint endpoint(GeoPoint point, PlaceEntity place) {
        return new RouteEditingContext.Endpoint(point.lat(), point.lon(), place == null ? null : PlaceMapper.toPlace(place));
    }

    private record ResolvedPlaces(List<PlaceEntity> stops, PlaceEntity start, PlaceEntity end) { }

    private static Route toRoute(RouteEntity entity) {
        var coordinates = entity.getPoints().stream().map(point -> List.of(point.lon(), point.lat())).toList();
        return new Route(entity.getId(), new Route.Geometry("LineString", coordinates), entity.getDistanceKm(),
                entity.getAscentM(), entity.getDurationMin(),
                entity.getPlaces().stream().map(PlaceMapper::toPlace).toList(), List.of());
    }
}
