package io.junction.trails.routes.web;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import io.junction.trails.routes.application.RoutingGateway;
import io.junction.trails.routes.cache.RoutingCacheKey;
import io.junction.trails.routes.persistence.RoutePersistence;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.DriverManager;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import org.springframework.transaction.CannotCreateTransactionException;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.images.builder.ImageFromDockerfile;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.utility.DockerImageName;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;

@Testcontainers
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = "spring.config.import=")
class RouteEditingApiTest {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final JsonNode EXAMPLES;
    private static final StubRoutingServer ORS;
    static {
        try {
            EXAMPLES = JSON.readTree(Files.readString(Path.of("../docs/contracts/route-editing.examples.json")));
            ORS = new StubRoutingServer();
        } catch (IOException exception) { throw new ExceptionInInitializerError(exception); }
    }

    @Container static final PostgreSQLContainer<?> DATABASE = new PostgreSQLContainer<>(
            DockerImageName.parse(new ImageFromDockerfile()
                    .withFileFromPath("Dockerfile", Path.of("../infra/postgres/Dockerfile"))
                    .withFileFromPath("init-extensions.sql", Path.of("../infra/postgres/init-extensions.sql"))
                    .get()).asCompatibleSubstituteFor("postgres"));
    @Container static final GenericContainer<?> VALKEY = new GenericContainer<>("valkey/valkey:8.1-alpine").withExposedPorts(6379);

    @DynamicPropertySource static void properties(DynamicPropertyRegistry p) {
        p.add("spring.datasource.url", DATABASE::getJdbcUrl);
        p.add("spring.datasource.username", DATABASE::getUsername);
        p.add("spring.datasource.password", DATABASE::getPassword);
        p.add("spring.data.redis.url", () -> "redis://" + VALKEY.getHost() + ":" + VALKEY.getMappedPort(6379));
        p.add("spring.data.redis.timeout", () -> "500ms");
        p.add("spring.data.redis.connect-timeout", () -> "500ms");
        p.add("routing.ors.base-url", ORS::baseUrl);
        p.add("routing.ors.api-key", () -> "fixture-key");
        p.add("routing.ors.read-timeout", () -> "500ms");
    }

    @Autowired TestRestTemplate http;
    @Autowired JdbcClient jdbc;
    @Autowired StringRedisTemplate valkey;
    @MockitoSpyBean RoutingGateway routing;
    @MockitoSpyBean RoutePersistence persistence;

    @BeforeEach void seed() throws Exception {
        ORS.reset();
        var keys = valkey.keys(RoutingCacheKey.PREFIX + "*");
        if (!keys.isEmpty()) { valkey.delete(keys); }
        jdbc.sql("TRUNCATE route_places, routes, places").update();
        var context = EXAMPLES.path("boundRead").path("response");
        var places = new java.util.ArrayList<JsonNode>();
        places.add(context.path("start").path("place"));
        context.path("stops").forEach(places::add);
        places.add(context.path("end").path("place"));
        for (var place : places) {
            jdbc.sql("""
                    INSERT INTO places(id,name,geom,tags,source) VALUES
                    (:id,:name,ST_SetSRID(ST_MakePoint(:lon,:lat),4326),
                    ARRAY(SELECT jsonb_array_elements_text(CAST(:tags AS jsonb))),:source)
                    """).param("id", UUID.fromString(place.path("id").asText()))
                    .param("name", place.path("name").asText()).param("lat", place.path("lat").asDouble())
                    .param("lon", place.path("lon").asDouble()).param("tags", place.path("tags").toString())
                    .param("source", place.path("source").asText()).update();
        }
        var example = EXAMPLES.path("rebuildReordered").path("response");
        ORS.respond(200, JSON.writeValueAsString(Map.of("type", "FeatureCollection", "features", List.of(Map.of(
                "type", "Feature", "geometry", example.path("geojson"), "properties", Map.of("summary", Map.of(
                        "distance", example.path("distanceKm").asDouble() * 1000,
                        "duration", example.path("durationMin").asDouble() * 60,
                        "ascent", example.path("ascentM").asDouble())))))), 0);
    }

    @AfterAll static void close() { ORS.close(); }

    @Test void sharedBoundFixturePersistsBefore201AndReturnsAnUnchangedRouteShape() {
        doAnswer(call -> {
            assertThat(TransactionSynchronizationManager.isActualTransactionActive()).isFalse();
            return call.callRealMethod();
        }).when(routing).route(any());
        var response = create(request());
        assertThat(response.getStatusCode().value()).isEqualTo(201);
        var route = response.getBody();
        ObjectNode expectedRoute = EXAMPLES.path("rebuildReordered").path("response").deepCopy();
        expectedRoute.put("id", route.path("id").asText());
        assertThat(route).isEqualTo(expectedRoute);
        ObjectNode expectedContext = EXAMPLES.path("rebuildReordered").path("subsequentEditingContext").deepCopy();
        expectedContext.put("routeId", route.path("id").asText());
        assertThat(context(route)).isEqualTo(expectedContext);
        assertThat(http.getForObject("/api/routes/" + route.path("id").asText(), JsonNode.class)).isEqualTo(route);
        assertThat(ORS.getRequests()).hasSize(1);
        assertThat(ORS.getRequests().getFirst().body().path("coordinates").toString())
                .isEqualTo("[[20.1,49.1],[20.12,49.12],[20.11,49.11],[20.13,49.13]]");
    }

    @Test void legacyCoordinatesAreNotInferredFromTrackOrNearbyKnownPlaces() {
        var legacy = request(); legacy.remove(List.of("startPlaceId", "endPlaceId"));
        var saved = create(legacy).getBody();
        var context = context(saved);
        assertThat(context.size()).isEqualTo(5);
        assertThat(context.path("start").path("lat").asDouble()).isEqualTo(49.1);
        assertThat(context.path("start").path("lon").asDouble()).isEqualTo(20.1);
        assertThat(context.path("start").path("place").isNull()).isTrue();
        assertThat(context.path("end").path("place").isNull()).isTrue();
        assertThat(saved.path("geojson").path("coordinates").get(0).get(1).asDouble()).isEqualTo(49.10005);
        assertThat(context.path("preferences")).isEqualTo(legacy.path("preferences"));
        assertThat(ORS.getRequests()).hasSize(1);
    }

    @ParameterizedTest @ValueSource(strings = {"startPlaceId", "endPlaceId", "both"})
    void acceptsNullOrSingleEndpointBindings(String clear) {
        var payload = request();
        if (clear.equals("both")) { payload.putNull("startPlaceId"); payload.putNull("endPlaceId"); }
        else { payload.putNull(clear); }
        var response = create(payload); assertThat(response.getStatusCode().value()).isEqualTo(201);
        var actual = context(response.getBody());
        assertThat(actual.path("start").path("place").isNull()).isEqualTo(clear.equals("startPlaceId") || clear.equals("both"));
        assertThat(actual.path("end").path("place").isNull()).isEqualTo(clear.equals("endPlaceId") || clear.equals("both"));
    }

    @Test void endpointMetadataDoesNotRekeyAWarmLegacyTrackAndReadsNeedNoCacheOrProvider() throws Exception {
        var legacy = request(); legacy.remove(List.of("startPlaceId", "endPlaceId"));
        var source = create(legacy).getBody(); var original = context(source);
        var key = valkey.keys(RoutingCacheKey.PREFIX + "*").iterator().next();
        valkey.expire(key, Duration.ofSeconds(45));
        ORS.respond(503, "{}", 0);
        var rebuilt = create(request()); assertThat(rebuilt.getStatusCode().value()).isEqualTo(201);
        assertThat(rebuilt.getBody().path("id")).isNotEqualTo(source.path("id"));
        assertThat(context(source)).isEqualTo(original);
        assertThat(context(rebuilt.getBody()).path("start").path("place").isObject()).isTrue();
        assertThat(valkey.keys(RoutingCacheKey.PREFIX + "*")).containsExactly(key);
        assertThat(valkey.getExpire(key)).isBetween(1L, 45L);
        assertThat(ORS.getRequests()).hasSize(1);
        VALKEY.execInContainer("valkey-cli", "CLIENT", "PAUSE", "5000", "ALL");
        try {
            assertThat(context(source)).isEqualTo(original);
            assertThat(http.getForObject("/api/routes/" + source.path("id").asText(), JsonNode.class)).isEqualTo(source);
        } finally { VALKEY.execInContainer("valkey-cli", "CLIENT", "UNPAUSE"); }
    }

    @Test void endpointBindingsCannotBypassValidationThroughAWarmTrackCache() {
        create(request());
        var invalid = EXAMPLES.path("coordinateMismatch").path("request");
        var response = create(invalid);
        problem(response, 400, "invalid_request");
        var missing = create(EXAMPLES.path("unknownEndpoint").path("request"));
        problem(missing, 422, "unknown_place");
        assertThat(ORS.getRequests()).hasSize(1);
        assertThat(routeCount()).isEqualTo(1);
        verify(routing, times(1)).route(any());
        assertThat(context(http.getForObject("/api/routes/" + lastId(), JsonNode.class)).path("start").path("place").isObject()).isTrue();
    }

    @ParameterizedTest @ValueSource(strings = {"startPlaceId", "endPlaceId"})
    void missingEndpointsFailBeforeAnyRouting(String field) {
        var payload = request(); payload.put(field, UUID.randomUUID().toString());
        problem(create(payload), 422, "unknown_place");
        assertNoWork();
    }

    @ParameterizedTest @ValueSource(strings = {"start", "end"})
    void coordinateBindingsHaveNoDistanceTolerance(String endpoint) {
        var payload = request();
        ObjectNode point = (ObjectNode) payload.path(endpoint);
        point.put("lon", point.path("lon").asDouble() + 0.000001);
        problem(create(payload), 400, "invalid_request");
        assertNoWork();
    }

    @Test void aSixthIntermediateVisitFailsBeforeRouting() {
        var payload = request(); var ids = payload.putArray("placeIds");
        for (int i = 0; i < 6; i++) { ids.add(EXAMPLES.path("boundRead").path("response").path("stops").get(0).path("id").asText()); }
        problem(create(payload), 400, "invalid_request");
        assertNoWork();
    }

    @ParameterizedTest @ValueSource(strings = {"\"\"", "\"bad\"", "\"1-1-1-1-1\"", "1", "true", "{}", "[]", "[\"00000000-0000-4000-8000-000000000001\"]"})
    void rejectsMalformedEndpointIdentitiesWithoutCoercingEmptyToNull(String value) throws Exception {
        var payload = request(); payload.set("startPlaceId", JSON.readTree(value));
        problem(create(payload), 400, "invalid_request");
        assertNoWork();
    }

    @Test void repeatsRoundTripsAndRemovalOperateOnOccurrencesWithoutEndpointInsertion() {
        var payload = request();
        var repeated = EXAMPLES.path("repeatedVisits").path("context").path("stops");
        var ids = payload.putArray("placeIds"); repeated.forEach(p -> ids.add(p.path("id").asText()));
        payload.set("end", payload.path("start").deepCopy());
        payload.set("endPlaceId", payload.path("startPlaceId").deepCopy());
        var original = create(payload).getBody(); var originalContext = context(original);
        assertThat(originalContext.path("stops")).isEqualTo(repeated);
        assertThat(originalContext.path("start")).isEqualTo(originalContext.path("end"));
        var fewer = request(); fewer.set("placeIds", EXAMPLES.path("repeatedVisits").path("requestAfterRemoval").path("placeIds"));
        var result = create(fewer).getBody();
        assertThat(context(result).path("stops").size()).isEqualTo(2);
        assertThat(context(original)).isEqualTo(originalContext);
        assertThat(ORS.getRequests().getFirst().body().path("coordinates").size()).isEqualTo(5);
    }

    @Test void rawEndpointSelectionClearsTheBindingAndAllStopsCanBeDeleted() {
        var payload = (ObjectNode) EXAMPLES.path("rawEndpointWrite").path("request").deepCopy();
        payload.putArray("placeIds");
        var response = create(payload); assertThat(response.getStatusCode().value()).isEqualTo(201);
        var context = context(response.getBody());
        assertThat(context.path("stops").isEmpty()).isTrue();
        assertThat(context.path("start").path("place").isNull()).isTrue();
        assertThat(context.path("end").path("place").isObject()).isTrue();
        assertThat(ORS.getRequests().getFirst().body().path("coordinates").size()).isEqualTo(2);
    }

    @Test void signedZeroBindsNumericallyWithoutMovingTheInput() {
        UUID id = UUID.fromString(request().path("startPlaceId").asText());
        jdbc.sql("UPDATE places SET geom=ST_SetSRID(ST_MakePoint(0,0),4326) WHERE id=:id").param("id", id).update();
        var payload = request(); payload.set("start", JSON.createObjectNode().put("lat", -0.0).put("lon", 0.0));
        var response = create(payload); assertThat(response.getStatusCode().value()).isEqualTo(201);
        assertThat(context(response.getBody()).path("start").path("place").path("id").asText()).isEqualTo(id.toString());
    }

    @ParameterizedTest @ValueSource(strings = {"?refresh=1", "?x=", "?x=1&x=2"})
    void editingContextRejectsAllQueryParameters(String query) {
        var route = create(request()).getBody();
        problem(http.getForEntity(path(route) + query, JsonNode.class), 400, "invalid_request");
    }

    @Test void missingMalformedAndUnavailableContextsHaveTheAgreedErrors() {
        problem(http.getForEntity("/api/routes/bad/editing-context", JsonNode.class), 400, "invalid_request");
        problem(http.getForEntity("/api/routes/" + UUID.randomUUID() + "/editing-context", JsonNode.class), 404, "route_not_found");
        doThrow(new CannotCreateTransactionException("fixture-private-password")).when(persistence).editingContext(any());
        var response = http.getForEntity("/api/routes/" + UUID.randomUUID() + "/editing-context", JsonNode.class);
        problem(response, 503, "storage_unavailable");
        assertThat(response.getBody().toString()).doesNotContain("fixture-private-password");
    }

    @ParameterizedTest @ValueSource(strings = {"1-1-1-1-1", "00000000000040008000000000000001"})
    void malformedContextIdsAreNotCoercedToAnotherUuid(String id) {
        problem(http.getForEntity("/api/routes/" + id + "/editing-context", JsonNode.class), 400, "invalid_request");
        assertNoWork();
    }

    @ParameterizedTest @CsvSource({"400,2009,422,no_hiking_route", "404,2010,422,waypoint_not_routable", "503,9999,502,routing_provider_error"})
    void failedRebuildsLeaveTheSourceRouteAndContextUntouched(int providerStatus, int providerCode, int status, String code) {
        var source = create(request()).getBody(); var original = context(source);
        ORS.respond(providerStatus, "{\"error\":{\"code\":" + providerCode + "}}", 0);
        var changed = request(); changed.putArray("placeIds");
        problem(create(changed), status, code);
        assertThat(routeCount()).isEqualTo(1);
        assertThat(context(source)).isEqualTo(original);
        assertThat(ORS.getRequests()).hasSize(2);
    }

    @Test void endpointForeignKeysPreventDeletionWithoutDeletingTheRoute() {
        var route = create(request()).getBody();
        assertThatThrownBy(() -> jdbc.sql("DELETE FROM places WHERE id=:id")
                .param("id", UUID.fromString(request().path("startPlaceId").asText())).update())
                .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThat(context(route).path("start").path("place").isObject()).isTrue();
        assertThat(routeCount()).isEqualTo(1);
    }

    @Test void editingContextSupportsFrontendCorsAndPreservesPreferenceValues() {
        var payload = request(); payload.putArray("preferences").add("  quiet scenery  ").add("quiet scenery").add("quiet scenery");
        var route = create(payload).getBody();
        var headers = new HttpHeaders(); headers.setOrigin("http://localhost:5173");
        var response = http.exchange(path(route), HttpMethod.GET, new HttpEntity<>(headers), JsonNode.class);
        assertThat(response.getStatusCode().value()).isEqualTo(200);
        assertThat(response.getHeaders().getAccessControlAllowOrigin()).isEqualTo("http://localhost:5173");
        assertThat(response.getBody().path("preferences")).isEqualTo(payload.path("preferences"));
    }

    @Test void storageFailureAfterRoutingDoesNotPartiallyInsertBindingsOrModifyTheSource() {
        var source = create(request()).getBody(); var original = context(source);
        doThrow(new CannotCreateTransactionException("fixture-private-password")).when(persistence).save(any(), any());
        var changed = request(); changed.putArray("placeIds");
        var response = create(changed); problem(response, 503, "storage_unavailable");
        assertThat(response.getBody().toString()).doesNotContain("fixture-private-password");
        assertThat(routeCount()).isEqualTo(1);
        assertThat(context(source)).isEqualTo(original);
        assertThat(ORS.getRequests()).hasSize(2);
    }

    @Test void providerTimeoutDoesNotRetryOrChangeTheSourceRoute() {
        var source = create(request()).getBody(); var original = context(source);
        ORS.delayBody(1500);
        var changed = request(); changed.putArray("placeIds");
        problem(create(changed), 504, "routing_timeout");
        assertThat(routeCount()).isEqualTo(1);
        assertThat(context(source)).isEqualTo(original);
        assertThat(ORS.getRequests()).hasSize(2);
    }

    @Test void corruptedSavedBindingFailsSafelyInsteadOfGuessingOrMovingTheEndpoint() {
        var route = create(request()).getBody();
        jdbc.sql("UPDATE routes SET start_geom=ST_SetSRID(ST_MakePoint(20,48),4326) WHERE id=:id")
                .param("id", UUID.fromString(route.path("id").asText())).update();
        var response = http.getForEntity(path(route), JsonNode.class);
        assertThat(response.getStatusCode().value()).isEqualTo(500);
        assertThat(response.getBody().has("routeId")).isFalse();
        assertThat(response.getBody().toString()).doesNotContain("SELECT", "jdbc:");
        assertThat(ORS.getRequests()).hasSize(1);
    }

    @Test void migrationUpgradesV3WithoutBackfillingEndpointIdentitiesOrChangingOriginalData() throws Exception {
        // This database belongs only to this disposable container, never the team's Aiven service.
        try (var admin = DriverManager.getConnection(DATABASE.getJdbcUrl(), DATABASE.getUsername(), DATABASE.getPassword());
             var sql = admin.createStatement()) { sql.execute("CREATE DATABASE editing_upgrade"); }
        String url = DATABASE.getJdbcUrl().replace("/" + DATABASE.getDatabaseName(), "/editing_upgrade");
        try (var connection = DriverManager.getConnection(url, DATABASE.getUsername(), DATABASE.getPassword());
             var sql = connection.createStatement()) { sql.execute("CREATE EXTENSION postgis"); sql.execute("CREATE EXTENSION vector"); }
        Flyway.configure().dataSource(url, DATABASE.getUsername(), DATABASE.getPassword()).target("3").load().migrate();
        try (var connection = DriverManager.getConnection(url, DATABASE.getUsername(), DATABASE.getPassword());
             var sql = connection.createStatement()) {
            sql.execute("""
                    INSERT INTO places(id,name,geom,tags,source) VALUES
                    ('00000000-0000-4000-8000-000000000001','Legacy',ST_SetSRID(ST_MakePoint(20,49),4326),ARRAY[]::text[],'manual');
                    INSERT INTO routes(id,geom,start_geom,end_geom,distance_km,ascent_m,duration_min,preferences) VALUES
                    ('10000000-0000-4000-8000-000000000001',ST_GeomFromText('LINESTRING(20.001 49.001,21.001 50.001)',4326),
                     ST_SetSRID(ST_MakePoint(20,49),4326),ST_SetSRID(ST_MakePoint(21,50),4326),10,100,120,ARRAY['quiet scenery']);
                    INSERT INTO route_places(route_id,position,place_id) VALUES
                    ('10000000-0000-4000-8000-000000000001',0,'00000000-0000-4000-8000-000000000001');
                    """);
        }
        assertThat(Flyway.configure().dataSource(url, DATABASE.getUsername(), DATABASE.getPassword()).load().migrate().migrationsExecuted).isEqualTo(1);
        try (var connection = DriverManager.getConnection(url, DATABASE.getUsername(), DATABASE.getPassword());
             var sql = connection.createStatement();
             var row = sql.executeQuery("SELECT start_place_id,end_place_id,ST_X(start_geom),ST_Y(end_geom),preferences[1],ST_X(ST_StartPoint(geom)),(SELECT count(*) FROM route_places) FROM routes")) {
            assertThat(row.next()).isTrue();
            assertThat(row.getObject(1)).isNull(); assertThat(row.getObject(2)).isNull();
            assertThat(row.getDouble(3)).isEqualTo(20); assertThat(row.getDouble(4)).isEqualTo(50);
            assertThat(row.getString(5)).isEqualTo("quiet scenery"); assertThat(row.getDouble(6)).isEqualTo(20.001);
            assertThat(row.getLong(7)).isEqualTo(1);
        }
    }

    private ObjectNode request() { return EXAMPLES.path("rebuildReordered").path("request").deepCopy(); }
    private ResponseEntity<JsonNode> create(JsonNode payload) { return http.postForEntity("/api/routes", payload, JsonNode.class); }
    private JsonNode context(JsonNode route) {
        var response = http.getForEntity(path(route), JsonNode.class);
        assertThat(response.getStatusCode().value()).isEqualTo(200);
        return response.getBody();
    }
    private String path(JsonNode route) { return "/api/routes/" + route.path("id").asText() + "/editing-context"; }
    private long routeCount() { return jdbc.sql("SELECT count(*) FROM routes").query(Long.class).single(); }
    private String lastId() { return jdbc.sql("SELECT id::text FROM routes LIMIT 1").query(String.class).single(); }
    private void assertNoWork() {
        assertThat(ORS.getRequests()).isEmpty();
        assertThat(valkey.keys(RoutingCacheKey.PREFIX + "*")).isEmpty();
        assertThat(routeCount()).isZero();
    }
    private static void problem(ResponseEntity<JsonNode> response, int status, String code) {
        assertThat(response.getStatusCode().value()).isEqualTo(status);
        assertThat(response.getBody().path("status").asInt()).isEqualTo(status);
        assertThat(response.getBody().path("code").asText()).isEqualTo(code);
        for (String field : List.of("type", "title", "detail")) { assertThat(response.getBody().path(field).asText()).isNotBlank(); }
    }
}
