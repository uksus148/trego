package io.junction.trails.routes.model;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;

class BaselineContractTest {
    @Test
    void sharedBaselineRetainsTheRouteShapeAndRepeatedPlaceOccurrences() throws Exception {
        var json = new ObjectMapper();
        var corpus = json.readTree(Files.readString(Path.of("../docs/contracts/baseline.examples.json")));
        Route route = json.treeToValue(corpus.get("route"), Route.class);
        assertThat(route.places()).extracting(p -> p.id().toString()).containsExactly(
                corpus.at("/places/1/id").asText(), corpus.at("/places/0/id").asText(), corpus.at("/places/1/id").asText());
        assertThat(route.geojson().coordinates().getFirst()).containsExactly(20.0, 49.0);
        assertThat(route.distanceKm()).isEqualTo(7.5);
        assertThat(route.places().getFirst().source()).isEqualTo("https://evidence.example/falls");
        assertThat(corpus.get("route").size()).isEqualTo(7);
    }
}
