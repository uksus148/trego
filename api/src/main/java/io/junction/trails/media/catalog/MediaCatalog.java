package io.junction.trails.media.catalog;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.junction.trails.media.model.MediaMetadata;
import io.junction.trails.media.model.OsmIdentity;
import java.io.IOException;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;
import org.slf4j.LoggerFactory;
import org.springframework.core.io.ResourceLoader;

public final class MediaCatalog {
    private final Map<OsmIdentity, MediaMetadata> entries;

    public MediaCatalog(ObjectMapper json, ResourceLoader loader, String location) {
        if (!(location.startsWith("classpath:") || location.startsWith("file:"))) {
            throw new IllegalArgumentException("The media catalog must be a local resource");
        }
        var values = new HashMap<OsmIdentity, MediaMetadata>();
        try (var input = loader.getResource(location).getInputStream()) {
            byte[] bytes = input.readNBytes(262145);
            if (bytes.length > 262144) { throw new IllegalArgumentException("Media catalog exceeds size limit"); }
            var root = json.readTree(bytes);
            if (root == null || !root.path("entries").isArray()) { throw new IllegalArgumentException("Invalid media catalog"); }
            int index = 0;
            for (var candidate : root.path("entries")) {
                try {
                    Entry checked = json.readerFor(Entry.class)
                            .with(DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES,
                                    DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                            .readValue(candidate);
                    if (checked.identity() == null || checked.metadata() == null || checked.metadata().photos().size() != 1
                            || checked.reviewEvidence() == null || checked.reviewEvidence().isBlank()) {
                        throw new IllegalArgumentException("Incomplete catalog review");
                    }
                    if (values.putIfAbsent(checked.identity(), checked.metadata()) != null) {
                        throw new IllegalArgumentException("Duplicate catalog identity");
                    }
                } catch (IOException | IllegalArgumentException exception) {
                    LoggerFactory.getLogger(MediaCatalog.class).warn("Rejected media catalog entry index={}", index);
                }
                index++;
            }
        } catch (IOException exception) {
            throw new IllegalStateException("Cannot read the local media catalog", exception);
        }
        entries = Map.copyOf(values);
    }

    public Optional<MediaMetadata> find(OsmIdentity identity) {
        return Optional.ofNullable(entries.get(identity));
    }

    public record Entry(OsmIdentity identity, MediaMetadata metadata, String reviewEvidence) { }
}
