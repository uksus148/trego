package io.junction.trails.media.model;

import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class MediaModelTest {
    @ParameterizedTest @ValueSource(strings = {"http://upload.wikimedia.org/photo.jpg", "https://upload.wikimedia.org.evil.test/p.jpg",
            "https://secret@upload.wikimedia.org/p.jpg", "https://upload.wikimedia.org:443/p.jpg",
            "https://upload.wikimedia.org/p.jpg?token=secret", "javascript:alert(1)", "https://upload.wikimedia.org/p.jpg#fragment"})
    void rejectsUnsafeImageUrls(String value) {
        assertThatThrownBy(() -> MediaUrls.image(value)).isInstanceOf(IllegalArgumentException.class);
    }

    @ParameterizedTest @ValueSource(strings = {"2.0", "2.5", "3.0", "4.0"})
    void matchesLicenseDesignationToVersionAndJurisdiction(String version) {
        assertThat(MediaUrls.license("CC BY-SA " + version, "https://creativecommons.org/licenses/by-sa/" + version + "/")).isTrue();
        assertThat(MediaUrls.license("CC BY " + version + " DE", "https://creativecommons.org/licenses/by/" + version + "/de/")).isTrue();
        assertThat(MediaUrls.license("CC BY " + version, "https://creativecommons.org/licenses/by-sa/" + version + "/")).isFalse();
    }

    @Test void permitsVerifiedPublicDomainReferencesWithoutInventingALicenseVersion() {
        assertThat(MediaUrls.license("CC0", "https://creativecommons.org/publicdomain/zero/1.0/")).isTrue();
        assertThat(MediaUrls.license("Public domain", "https://commons.wikimedia.org/wiki/Commons:Public_domain")).isTrue();
        assertThat(MediaUrls.license("See source", "https://commons.wikimedia.org/wiki/Commons:Public_domain")).isFalse();
    }

    @Test void responseCannotClaimReadyWithoutPhotos() {
        assertThatThrownBy(() -> new MediaResponse(UUID.randomUUID(), "ready", null, null, List.of()))
                .isInstanceOf(IllegalArgumentException.class);
        assertThat(MediaResponse.of(UUID.randomUUID(), MediaMetadata.empty()).status()).isEqualTo("empty");
    }

    @Test void locationAndIdentityRejectInvalidData() {
        assertThatThrownBy(() -> new OsmIdentity("node", 0)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> new OsmIdentity("photo", 123)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> new MediaMetadata.PhotoLocation(Double.NaN, 20)).isInstanceOf(IllegalArgumentException.class);
    }
}
