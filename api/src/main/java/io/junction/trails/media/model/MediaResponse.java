package io.junction.trails.media.model;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

public record MediaResponse(UUID placeId, String status, Instant fetchedAt,
                            MediaMetadata.SourcedText placeDescription, List<MediaMetadata.LandmarkPhoto> photos) {
    public MediaResponse {
        java.util.Objects.requireNonNull(placeId, "placeId");
        photos = List.copyOf(photos);
        if (photos.size() > 1 || !(photos.isEmpty() ? "empty" : "ready").equals(status)
                || (!photos.isEmpty() && fetchedAt == null)) {
            throw new IllegalArgumentException("Inconsistent media response");
        }
    }

    public static MediaResponse of(UUID id, MediaMetadata metadata) {
        return new MediaResponse(id, metadata.photos().isEmpty() ? "empty" : "ready",
                metadata.fetchedAt(), metadata.placeDescription(), metadata.photos());
    }
}
