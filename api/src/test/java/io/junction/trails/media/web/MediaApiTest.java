package io.junction.trails.media.web;

import com.fasterxml.jackson.databind.JsonNode;
import io.junction.trails.media.cache.CachedPhotoDiscovery;
import io.junction.trails.media.integration.MediaFixtureServer;
import io.junction.trails.media.persistence.MediaPlaceReader;
import java.nio.file.Path;
import java.time.Duration;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import org.springframework.transaction.CannotCreateTransactionException;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.images.builder.ImageFromDockerfile;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.utility.DockerImageName;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.doThrow;

@Testcontainers
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {"spring.config.import=", "API_MEDIA_ENABLED=true", "API_MEDIA_CATALOG=classpath:media/catalog-fixture.json"})
class MediaApiTest {
    static final String ROOT = "/api/places/";
    static final String AUTO = "00000000-0000-4000-8000-000000000001";
    static final String MANUAL = "00000000-0000-4000-8000-000000000002";
    static final String CURATED = "00000000-0000-4000-8000-000000000003";
    static final MediaFixtureServer PROVIDERS;
    static {
        try { PROVIDERS = new MediaFixtureServer(); }
        catch (java.io.IOException exception) { throw new ExceptionInInitializerError(exception); }
    }

    @Container static final PostgreSQLContainer<?> DB = new PostgreSQLContainer<>(DockerImageName.parse(
            new ImageFromDockerfile().withFileFromPath("Dockerfile", Path.of("../infra/postgres/Dockerfile"))
                    .withFileFromPath("init-extensions.sql", Path.of("../infra/postgres/init-extensions.sql"))
                    .get()).asCompatibleSubstituteFor("postgres"));
    @Container static final GenericContainer<?> VALKEY = new GenericContainer<>("valkey/valkey:8.1-alpine").withExposedPorts(6379);

    @DynamicPropertySource static void properties(DynamicPropertyRegistry p) {
        p.add("spring.datasource.url", DB::getJdbcUrl);
        p.add("spring.datasource.username", DB::getUsername);
        p.add("spring.datasource.password", DB::getPassword);
        p.add("spring.data.redis.url", () -> "redis://" + VALKEY.getHost() + ":" + VALKEY.getMappedPort(6379));
        p.add("spring.data.redis.timeout", () -> "500ms");
        p.add("spring.data.redis.connect-timeout", () -> "500ms");
        p.add("API_MEDIA_NOMINATIM_BASE_URL", () -> PROVIDERS.base().toString());
        p.add("API_MEDIA_WIKIDATA_URL", () -> PROVIDERS.base().resolve("/wikidata").toString());
        p.add("API_MEDIA_COMMONS_URL", () -> PROVIDERS.base().resolve("/commons").toString());
        p.add("API_MEDIA_LOOKUP_TIMEOUT", () -> "2s");
        p.add("API_MEDIA_CONNECT_TIMEOUT", () -> "200ms");
    }

    @Autowired TestRestTemplate http;
    @Autowired JdbcClient jdbc;
    @Autowired StringRedisTemplate redis;
    @MockitoSpyBean MediaPlaceReader reader;

    @BeforeEach void setup() {
        PROVIDERS.reset();
        jdbc.sql("TRUNCATE route_places, routes, places").update();
        jdbc.sql("""
                INSERT INTO places(id,name,geom,tags,source,osm_type,osm_id) VALUES
                (CAST(:auto AS uuid),'Automatic fixture',ST_SetSRID(ST_MakePoint(20,49),4326),ARRAY['waterfall'],
                    'https://example.org/fixture','node',42),
                (CAST(:manual AS uuid),'Manual fixture',ST_SetSRID(ST_MakePoint(20,49),4326),ARRAY[]::text[],'manual',null,null),
                (CAST(:curated AS uuid),'Curated fixture',ST_SetSRID(ST_MakePoint(20,49),4326),ARRAY[]::text[],
                    'https://example.org/fixture','way',84)
                """).param("auto", AUTO).param("manual", MANUAL).param("curated", CURATED).update();
        redis.execute((org.springframework.data.redis.core.RedisCallback<Void>) connection -> {
            connection.serverCommands().flushDb(); return null;
        });
    }

    @AfterAll static void close() { PROVIDERS.close(); }

    @Test void fullHttpDiscoveryReturnsTheAgreedShapeAndLeavesExistingPlacesAndRoutesUnchanged() {
        var headers = new HttpHeaders(); headers.setOrigin("http://localhost:5173");
        var response = http.exchange(ROOT + AUTO + "/media", HttpMethod.GET, new HttpEntity<>(headers), JsonNode.class);
        assertThat(response.getStatusCode().value()).isEqualTo(200);
        assertThat(response.getHeaders().getAccessControlAllowOrigin()).isEqualTo("http://localhost:5173");
        JsonNode body = response.getBody();
        assertThat(body.size()).isEqualTo(5);
        assertThat(body.path("placeId").asText()).isEqualTo(AUTO);
        assertThat(body.path("status").asText()).isEqualTo("ready");
        assertThat(body.path("photos").size()).isEqualTo(1);
        assertThat(body.path("photos").get(0).path("photoLocation").isNull()).isTrue();
        assertThat(body.path("placeDescription").path("sourceUrl").asText()).isEqualTo("https://www.wikidata.org/wiki/Q42");
        assertThat(PROVIDERS.requests).hasSize(3);
        assertThat(jdbc.sql("SELECT count(*) FROM places").query(Long.class).single()).isEqualTo(3);
        assertThat(jdbc.sql("SELECT count(*) FROM routes").query(Long.class).single()).isZero();
        assertThat(redis.keys("trego:routes:*")).isEmpty();
    }

    @Test void manualPlaceIsEmptyWithoutAnyProviderOrCacheCalls() {
        var body = http.getForObject(ROOT + MANUAL + "/media", JsonNode.class);
        assertThat(body.path("status").asText()).isEqualTo("empty");
        assertThat(body.path("photos").isEmpty()).isTrue();
        assertThat(body.path("fetchedAt").isNull()).isTrue();
        assertThat(body.has("placeDescription")).isTrue();
        assertThat(PROVIDERS.requests).isEmpty();
        assertThat(redis.keys("*")).isEmpty();
    }

    @Test void reviewedCatalogTakesPriorityAndDoesNotNeedExternalProviders() {
        var body = http.getForObject(ROOT + CURATED + "/media", JsonNode.class);
        assertThat(body.path("photos").get(0).path("id").asText()).isEqualTo("commons:456");
        assertThat(body.path("fetchedAt").asText()).isEqualTo("2026-11-15T00:00:00Z");
        assertThat(PROVIDERS.requests).isEmpty();
        assertThat(redis.keys("*")).isEmpty();
    }

    @Test void cacheHitRetainsRetrievalTimeAndTtlWithoutProviderWorkEvenForAnotherDatabaseUuid() {
        JsonNode first = http.getForObject(ROOT + AUTO + "/media", JsonNode.class);
        String key = redis.keys(CachedPhotoDiscovery.PREFIX + "*").iterator().next();
        redis.expire(key, Duration.ofSeconds(45));
        String newId = UUID.randomUUID().toString();
        jdbc.sql("UPDATE places SET id=CAST(:id AS uuid) WHERE id=CAST(:old AS uuid)")
                .param("id", newId).param("old", AUTO).update();
        PROVIDERS.requests.clear();
        var second = http.getForObject(ROOT + newId + "/media", JsonNode.class);
        assertThat(second.path("placeId").asText()).isEqualTo(newId);
        assertThat(second.path("fetchedAt")).isEqualTo(first.path("fetchedAt"));
        assertThat(redis.getExpire(key)).isBetween(1L, 45L);
        assertThat(PROVIDERS.requests).isEmpty();
    }

    @Test void positiveAndNegativeResultsHaveDifferentBoundedTtls() {
        http.getForObject(ROOT + AUTO + "/media", JsonNode.class);
        String key = redis.keys(CachedPhotoDiscovery.PREFIX + "*").iterator().next();
        assertThat(redis.getExpire(key)).isBetween(86380L, 86400L);
        redis.delete(key);
        PROVIDERS.reply("/lookup", 200, "[]", 0);
        http.getForObject(ROOT + AUTO + "/media", JsonNode.class);
        assertThat(redis.getExpire(key)).isBetween(280L, 300L);
    }

    @Test void corruptCacheIsRefreshedOnceWithoutGlobalDeletion() {
        http.getForObject(ROOT + AUTO + "/media", JsonNode.class);
        String key = redis.keys(CachedPhotoDiscovery.PREFIX + "*").iterator().next();
        redis.opsForValue().set(key, "{broken");
        redis.opsForValue().set("unrelated-key", "retained");
        PROVIDERS.requests.clear();
        assertThat(http.getForEntity(ROOT + AUTO + "/media", JsonNode.class).getStatusCode().value()).isEqualTo(200);
        assertThat(PROVIDERS.requests).hasSize(3);
        assertThat(redis.opsForValue().get("unrelated-key")).isEqualTo("retained");
    }

    @ParameterizedTest @ValueSource(strings = {"?refresh=true", "?provider=other", "?x=", "?x=1&x=2"})
    void rejectsUnsupportedParametersBeforeWork(String query) {
        var r = http.getForEntity(ROOT + AUTO + "/media" + query, JsonNode.class);
        assertThat(r.getStatusCode().value()).isEqualTo(400);
        assertThat(r.getBody().path("code").asText()).isEqualTo("invalid_request");
        assertThat(PROVIDERS.requests).isEmpty();
    }

    @Test void badAndUnknownUuidsAreDistinct() {
        assertThat(http.getForEntity(ROOT + "not-a-uuid/media", JsonNode.class).getStatusCode().value()).isEqualTo(400);
        var r = http.getForEntity(ROOT + UUID.randomUUID() + "/media", JsonNode.class);
        assertThat(r.getStatusCode().value()).isEqualTo(404);
        assertThat(r.getBody().path("code").asText()).isEqualTo("place_not_found");
        assertThat(PROVIDERS.requests).isEmpty();
    }

    @Test void upstreamErrorIsSafeNotCachedAndDoesNotBecomeEmptyOrChangeRoutes() {
        PROVIDERS.reply("/lookup", 503, "{\"error\":\"fixture-private-password\"}", 0);
        var r = http.getForEntity(ROOT + AUTO + "/media", JsonNode.class);
        assertThat(r.getStatusCode().value()).isEqualTo(502);
        assertThat(r.getBody().path("code").asText()).isEqualTo("photo_provider_error");
        assertThat(r.getBody().toString()).doesNotContain("fixture-private-password");
        assertThat(redis.keys(CachedPhotoDiscovery.PREFIX + "*")).isEmpty();
        assertThat(jdbc.sql("SELECT count(*) FROM routes").query(Long.class).single()).isZero();
    }

    @Test void storageFailureRemainsSafe503() {
        doThrow(new CannotCreateTransactionException("fixture-private-password"))
                .when(reader).identity(UUID.fromString(AUTO));
        var r = http.getForEntity(ROOT + AUTO + "/media", JsonNode.class);
        assertThat(r.getStatusCode().value()).isEqualTo(503);
        assertThat(r.getBody().path("code").asText()).isEqualTo("storage_unavailable");
        assertThat(r.getBody().toString()).doesNotContain("fixture-private-password");
    }

    @Test void totalBudgetIncludesStalledResponseBodies() {
        PROVIDERS.reply("/lookup", 200, "[]", 3000);
        var r = http.getForEntity(ROOT + AUTO + "/media", JsonNode.class);
        assertThat(r.getStatusCode().value()).isEqualTo(504);
        assertThat(r.getBody().path("code").asText()).isEqualTo("photo_timeout");
        assertThat(PROVIDERS.requests).hasSize(1);
        assertThat(redis.keys(CachedPhotoDiscovery.PREFIX + "*")).isEmpty();
    }

    @Test void honorsTheAgentsExistingNominatimTokenAndCooldownNamespace() throws Exception {
        String hash = java.util.HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256")
                .digest(PROVIDERS.base().toString().getBytes(java.nio.charset.StandardCharsets.UTF_8)));
        String key = "gopstop:nominatim:gate:v1:" + hash;
        redis.opsForValue().set(key, "agent-token", Duration.ofMillis(250));
        long started = System.nanoTime();
        var r = http.getForEntity(ROOT + AUTO + "/media", JsonNode.class);
        assertThat(r.getStatusCode().value()).isEqualTo(200);
        assertThat(Duration.ofNanos(System.nanoTime() - started)).isGreaterThan(Duration.ofMillis(150));
        assertThat(PROVIDERS.requests.stream().filter(uri -> uri.getPath().equals("/lookup"))).hasSize(1);
        assertThat(redis.getExpire(key, java.util.concurrent.TimeUnit.MILLISECONDS)).isBetween(1L, 1000L);
    }

    @Test void cooldownDoesNotShortenAnotherOwnersLease() throws Exception {
        String hash = java.util.HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256")
                .digest(PROVIDERS.base().toString().getBytes(java.nio.charset.StandardCharsets.UTF_8)));
        String key = "gopstop:nominatim:gate:v1:" + hash;
        var gate = new io.junction.trails.media.cache.NominatimGate(redis, PROVIDERS.base());
        String result = gate.call(new io.junction.trails.media.application.MediaDeadline(Duration.ofSeconds(2)), () -> {
            redis.opsForValue().set(key, "other-owner", Duration.ofSeconds(6));
            return "ok";
        });
        assertThat(result).isEqualTo("ok");
        assertThat(redis.opsForValue().get(key)).isEqualTo("other-owner");
        assertThat(redis.getExpire(key)).isBetween(4L, 6L);
    }

    @Test void requiredCacheFailurePreventsOutboundDiscovery() throws Exception {
        VALKEY.execInContainer("valkey-cli", "CLIENT", "PAUSE", "1200", "ALL");
        var r = http.getForEntity(ROOT + AUTO + "/media", JsonNode.class);
        assertThat(r.getStatusCode().value()).isEqualTo(503);
        assertThat(r.getBody().path("code").asText()).isEqualTo("cache_unavailable");
        assertThat(PROVIDERS.requests).isEmpty();
        Thread.sleep(900);
    }
}
