package io.junction.trails.media.model;

import java.time.Instant;
import java.util.List;

public record MediaMetadata(Instant fetchedAt, SourcedText placeDescription, List<LandmarkPhoto> photos) {
    public MediaMetadata {
        photos = List.copyOf(photos);
        if (photos.size() > 1 || (!photos.isEmpty() && fetchedAt == null)) {
            throw new IllegalArgumentException("Media must contain at most one attributed image with retrieval time");
        }
    }

    public static MediaMetadata empty() {
        return new MediaMetadata(null, null, List.of());
    }

    public record SourcedText(String text, String sourceUrl) {
        public SourcedText {
            if (text == null || text.isBlank() || text.length() > 1000) {
                throw new IllegalArgumentException("Invalid sourced description");
            }
            MediaUrls.reference(sourceUrl);
        }
    }

    public record PhotoLocation(double lat, double lon) {
        public PhotoLocation {
            if (!Double.isFinite(lat) || !Double.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) {
                throw new IllegalArgumentException("Invalid photo geotag");
            }
        }
    }

    public record LandmarkPhoto(String id, String provider, String url, String thumbUrl, String title,
                                SourcedText description, String author, String license, String licenseUrl,
                                String sourceUrl, String associationSourceUrl, PhotoLocation photoLocation) {
        public LandmarkPhoto {
            if (id == null || !id.matches("commons:[1-9][0-9]*") || !"wikimedia_commons".equals(provider)) {
                throw new IllegalArgumentException("Invalid photo identity");
            }
            MediaUrls.image(url);
            MediaUrls.thumbnail(thumbUrl);
            MediaUrls.commonsPage(sourceUrl);
            MediaUrls.reference(associationSourceUrl);
            if (title == null || title.isBlank() || title.length() > 300
                    || author == null || author.isBlank() || author.length() > 500
                    || !MediaUrls.license(license, licenseUrl)) {
                throw new IllegalArgumentException("Incomplete or unsupported photo attribution");
            }
        }
    }
}
