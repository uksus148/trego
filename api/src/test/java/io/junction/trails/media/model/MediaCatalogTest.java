package io.junction.trails.media.model;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.junction.trails.media.catalog.MediaCatalog;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.DefaultResourceLoader;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class MediaCatalogTest {
    @Test void allFiveRealCatalogRecordsPassTheSameValidationAsAutomaticDiscovery() {
        var catalog = new MediaCatalog(new ObjectMapper().findAndRegisterModules(), new DefaultResourceLoader(), "classpath:media/catalog.json");
        for (var identity : java.util.List.of(new OsmIdentity("way", 4816134), new OsmIdentity("node", 383862401),
                new OsmIdentity("way", 33458143), new OsmIdentity("way", 1128350263), new OsmIdentity("relation", 16609274))) {
            assertThat(catalog.find(identity)).isPresent().hasValueSatisfying(value -> {
                assertThat(value.photos()).hasSize(1);
                assertThat(value.fetchedAt()).isNotNull();
                assertThat(value.photos().getFirst().photoLocation()).isNull();
            });
        }
        assertThat(catalog.find(new OsmIdentity("node", 4816134))).isEmpty();
    }

    @Test void catalogDoesNotFetchRemoteResourcesAtStartup() {
        assertThatThrownBy(() -> new MediaCatalog(new ObjectMapper(), new DefaultResourceLoader(), "https://example.org/private"))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
