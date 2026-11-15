package io.junction.trails.media.integration;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.junction.trails.media.application.MediaDeadline;
import io.junction.trails.media.cache.NominatimGate;
import io.junction.trails.media.model.MediaException;
import io.junction.trails.media.model.OsmIdentity;
import java.net.http.HttpClient;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.function.Supplier;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;

class WikimediaPhotoDiscoveryTest {
    MediaFixtureServer server;
    WikimediaPhotoDiscovery provider;

    @BeforeEach void setup() throws Exception {
        server = new MediaFixtureServer();
        var properties = new MediaProperties(server.base(), server.base().resolve("/wikidata"),
                server.base().resolve("/commons"), "trego-fixture/1.0", Duration.ofSeconds(2),
                Duration.ofMillis(200), "classpath:media/catalog.json", true);
        var gate = mock(NominatimGate.class);
        doAnswer(call -> ((Supplier<?>) call.getArgument(1)).get()).when(gate).call(any(), any());
        var http = new MediaHttpClient(HttpClient.newBuilder().connectTimeout(Duration.ofMillis(200))
                .followRedirects(HttpClient.Redirect.NEVER).build(), new ObjectMapper(), "trego-fixture/1.0");
        provider = new WikimediaPhotoDiscovery(http, gate, properties,
                Clock.fixed(Instant.parse("2026-11-15T00:00:00Z"), ZoneOffset.UTC));
    }

    @AfterEach void close() { server.close(); }

    @Test void followsExactOsmIdentityP18AndMetadataWithoutInventingCoordinates() {
        var result = find();
        assertThat(result.photos()).hasSize(1);
        var photo = result.photos().getFirst();
        assertThat(photo.id()).isEqualTo("commons:123");
        assertThat(photo.photoLocation()).isNull();
        assertThat(photo.author()).isEqualTo("Fixture creator");
        assertThat(photo.description().text()).isEqualTo("A fixture image & caption");
        assertThat(photo.associationSourceUrl()).isEqualTo("https://www.wikidata.org/wiki/Q42");
        assertThat(result.placeDescription().text()).isEqualTo("A fixture waterfall");
        assertThat(server.requests).hasSize(3);
        assertThat(server.requests.getFirst().getQuery()).contains("osm_ids=N42", "extratags=1");
        assertThat(server.requests.getLast().getQuery()).contains("titles=File:Fixture.jpg");
    }

    @Test void hasInformationEvenWhenThereIsNoP18Image() {
        server.reply("/wikidata", 200, """
                {"entities":{"Q42":{"id":"Q42","claims":{},"descriptions":{"en":{"value":"A known waterfall"}}}}}
                """, 0);
        var result = find();
        assertThat(result.photos()).isEmpty();
        assertThat(result.placeDescription().text()).isEqualTo("A known waterfall");
        assertThat(server.requests).hasSize(2);
    }

    @Test void missingOsmOrWikidataLinkIsAnHonestEmptyLookup() {
        server.reply("/lookup", 200, "[]", 0);
        assertThat(find().photos()).isEmpty();
        assertThat(server.requests).hasSize(1);
    }

    @Test void wrongOsmIdentityCannotLeadToAnImage() {
        server.reply("/lookup", 200, "[{\"osm_type\":\"way\",\"osm_id\":42}]", 0);
        assertThatThrownBy(this::find).isInstanceOf(MediaException.class)
                .hasFieldOrPropertyWithValue("reason", MediaException.Reason.PHOTO_PROVIDER_ERROR);
        assertThat(server.requests).hasSize(1);
    }

    @ParameterizedTest @ValueSource(strings = {"2.0", "2.5", "3.0", "4.0"})
    void retainsSupportedOriginalLicenseVersions(String version) {
        server.reply("/commons", 200, MediaFixtureServer.commons().replace("3.0", version), 0);
        assertThat(find().photos().getFirst().license()).isEqualTo("CC BY-SA " + version);
    }

    @ParameterizedTest @ValueSource(strings = {
            "image/svg+xml", "Unknown author", "http://evil.example/image.jpg", "CC BY-SA 1.0"
    })
    void rejectsUnsupportedOrUnsafeCandidateRatherThanReplacingIt(String bad) {
        String original = bad.equals("image/svg+xml") ? "image/jpeg"
                : bad.equals("Unknown author") ? "Fixture creator"
                : bad.startsWith("http") ? "https://upload.wikimedia.org/fixture-full.jpg" : "CC BY-SA 3.0";
        server.reply("/commons", 200, MediaFixtureServer.commons().replace(original, bad), 0);
        assertThat(find().photos()).isEmpty();
        assertThat(find().placeDescription()).isNotNull();
    }

    @ParameterizedTest @ValueSource(strings = {"/lookup", "/wikidata", "/commons"})
    void dependencyFailureIsNotEmptyAndDoesNotRetry(String path) {
        server.reply(path, 429, "{\"error\":\"private-key-do-not-echo\"}", 0);
        assertThatThrownBy(this::find).isInstanceOf(MediaException.class)
                .hasMessage("Photo metadata is temporarily unavailable.");
        assertThat(server.requests.stream().filter(uri -> uri.getPath().equals(path))).hasSize(1);
    }

    @Test void redirectsAreRejectedWithoutFollowingThem() {
        server.reply("/lookup", 302, "{}", 0);
        assertThatThrownBy(this::find).isInstanceOf(MediaException.class);
        assertThat(server.requests).hasSize(1);
    }

    @Test void deadlineIncludesDelayedBodyAndPreventsLaterHops() {
        server.reply("/lookup", 200, "[]", 600);
        long start = System.nanoTime();
        assertThatThrownBy(() -> provider.find(new OsmIdentity("node", 42), new MediaDeadline(Duration.ofMillis(100))))
                .isInstanceOf(MediaException.class).hasFieldOrPropertyWithValue("reason", MediaException.Reason.PHOTO_TIMEOUT);
        assertThat(Duration.ofNanos(System.nanoTime() - start)).isLessThan(Duration.ofMillis(550));
        assertThat(server.requests).hasSize(1);
    }

    @Test void boundsTheResponseBody() {
        server.reply("/lookup", 200, " ".repeat(1_100_000), 0);
        assertThatThrownBy(this::find).isInstanceOf(MediaException.class)
                .hasFieldOrPropertyWithValue("reason", MediaException.Reason.PHOTO_PROVIDER_ERROR);
    }

    @Test void supportsActualCommonsTrackingUrlsAndLicenseUrlsWithoutTrailingSlash() {
        String body = MediaFixtureServer.commons().replace("fixture-full.jpg", "fixture-full.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original")
                .replace("https://upload.wikimedia.org/fixture-thumb.jpg", "https://thumb.wikimedia.org/fixture-thumb.jpg?utm_content=thumbnail")
                .replace("https://creativecommons.org/licenses/by-sa/3.0/", "http://creativecommons.org/licenses/by-sa/3.0");
        server.reply("/commons", 200, body, 0);
        var photo = find().photos().getFirst();
        assertThat(photo.url()).isEqualTo("https://upload.wikimedia.org/fixture-full.jpg");
        assertThat(photo.licenseUrl()).isEqualTo("https://creativecommons.org/licenses/by-sa/3.0");
        assertThat(photo.thumbUrl()).isEqualTo("https://thumb.wikimedia.org/fixture-thumb.jpg");
    }

    @Test void doesNotStripUnknownTokenParametersToMakeAnUnsafeImageAppearValid() {
        server.reply("/commons", 200, MediaFixtureServer.commons().replace("fixture-full.jpg", "fixture-full.jpg?token=secret"), 0);
        assertThat(find().photos()).isEmpty();
    }

    @Test void rejectsMismatchedEntityAndImageSourceIdentities() {
        server.reply("/commons", 200, MediaFixtureServer.commons()
                .replace("wiki/File:Fixture.jpg", "wiki/File:Different.jpg"), 0);
        assertThat(find().photos()).isEmpty();
        server.reply("/wikidata", 200, "{\"entities\":{\"Q42\":{\"id\":\"Q99\",\"claims\":{}}}}", 0);
        assertThatThrownBy(this::find).isInstanceOf(MediaException.class);
    }

    private io.junction.trails.media.model.MediaMetadata find() {
        return provider.find(new OsmIdentity("node", 42), new MediaDeadline(Duration.ofSeconds(2)));
    }
}
