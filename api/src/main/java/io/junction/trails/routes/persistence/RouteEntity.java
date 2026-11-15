package io.junction.trails.routes.persistence;

import io.junction.trails.places.persistence.PlaceEntity;
import io.junction.trails.routes.model.GeoPoint;
import io.junction.trails.routes.model.NewRoute;
import io.junction.trails.routes.model.RouteCreation;
import io.junction.trails.routes.model.RouteTrack;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.JoinTable;
import jakarta.persistence.ManyToMany;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.FetchType;
import jakarta.persistence.OrderColumn;
import jakarta.persistence.Table;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.UUID;
import java.util.Objects;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;
import org.locationtech.jts.geom.Coordinate;
import org.locationtech.jts.geom.GeometryFactory;
import org.locationtech.jts.geom.LineString;
import org.locationtech.jts.geom.Point;
import org.locationtech.jts.geom.PrecisionModel;

@Entity
@Table(name = "routes")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class RouteEntity {
    private static final GeometryFactory WGS84 = new GeometryFactory(new PrecisionModel(), 4326);

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    @Getter
    private UUID id;

    @Column(name = "geom", nullable = false, columnDefinition = "geometry(LineString,4326)")
    private LineString geometry;

    @Column(name = "start_geom", nullable = false, columnDefinition = "geometry(Point,4326)")
    private Point startGeom;

    @Column(name = "end_geom", nullable = false, columnDefinition = "geometry(Point,4326)")
    private Point endGeom;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "start_place_id")
    @Getter
    private PlaceEntity startPlace;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "end_place_id")
    @Getter
    private PlaceEntity endPlace;

    @Column(name = "distance_km", nullable = false)
    @Getter
    private double distanceKm;

    @Column(name = "ascent_m", nullable = false)
    @Getter
    private double ascentM;

    @Column(name = "duration_min", nullable = false)
    @Getter
    private double durationMin;

    @JdbcTypeCode(SqlTypes.ARRAY)
    @Column(nullable = false, columnDefinition = "text[]")
    private String[] preferences;

    @ManyToMany
    @JoinTable(name = "route_places", joinColumns = @JoinColumn(name = "route_id"),
            inverseJoinColumns = @JoinColumn(name = "place_id"))
    @OrderColumn(name = "position", nullable = false)
    private List<PlaceEntity> places;

    public RouteEntity(RouteCreation creation, RouteTrack track, List<PlaceEntity> places,
                       PlaceEntity startPlace, PlaceEntity endPlace) {
        NewRoute request = creation.routingRequest();
        if (!places.stream().map(PlaceEntity::getId).toList().equals(request.placeIds())) {
            throw new IllegalArgumentException("Persisted route stops must match the requested visits");
        }
        checkBinding(creation.startPlaceId(), startPlace, request.start());
        checkBinding(creation.endPlaceId(), endPlace, request.end());
        this.startPlace = startPlace;
        this.endPlace = endPlace;
        geometry = WGS84.createLineString(track.points().stream().map(RouteEntity::coordinate).toArray(Coordinate[]::new));
        startGeom = WGS84.createPoint(coordinate(request.start()));
        endGeom = WGS84.createPoint(coordinate(request.end()));
        distanceKm = track.distanceKm();
        ascentM = track.ascentM();
        durationMin = track.durationMin();
        preferences = request.preferences().toArray(String[]::new);
        this.places = new ArrayList<>(places);
    }

    public List<GeoPoint> getPoints() {
        return Arrays.stream(geometry.getCoordinates()).map(point -> new GeoPoint(point.y, point.x)).toList();
    }

    public List<PlaceEntity> getPlaces() {
        return List.copyOf(places);
    }

    public GeoPoint getStart() { return new GeoPoint(startGeom.getY(), startGeom.getX()); }

    public GeoPoint getEnd() { return new GeoPoint(endGeom.getY(), endGeom.getX()); }

    public List<String> getPreferences() { return List.copyOf(Arrays.asList(preferences)); }

    private static void checkBinding(UUID expected, PlaceEntity place, GeoPoint point) {
        if (!Objects.equals(expected, place == null ? null : place.getId())
                || place != null && (place.getLat() != point.lat() || place.getLon() != point.lon())) {
            throw new IllegalArgumentException("Persisted endpoint must match its requested place binding");
        }
    }

    private static Coordinate coordinate(GeoPoint point) {
        return new Coordinate(point.lon(), point.lat());
    }
}
