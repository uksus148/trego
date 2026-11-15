package io.junction.trails.media.application;

import io.junction.trails.media.catalog.MediaCatalog;
import io.junction.trails.media.model.MediaException;
import io.junction.trails.media.model.MediaMetadata;
import io.junction.trails.media.model.OsmIdentity;
import io.junction.trails.media.persistence.MediaPlaceReader;
import java.time.Duration;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

class MediaServiceTest {
    @Test void callerDeadlineInterruptsQueuedOrRunningDiscoveryInsteadOfLeavingALateRequest() throws Exception {
        var places = mock(MediaPlaceReader.class);
        var catalog = mock(MediaCatalog.class);
        var discovery = mock(PhotoDiscovery.class);
        var id = UUID.randomUUID(); var identity = new OsmIdentity("node", 42);
        when(places.identity(id)).thenReturn(identity);
        when(catalog.find(identity)).thenReturn(Optional.empty());
        var cancelled = new CountDownLatch(1);
        when(discovery.find(any(), any())).thenAnswer(call -> {
            try { Thread.sleep(2000); }
            catch (InterruptedException exception) { cancelled.countDown(); Thread.currentThread().interrupt(); }
            return MediaMetadata.empty();
        });
        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            var service = new MediaService(places, catalog, discovery, executor, Duration.ofMillis(200), true);
            assertThatThrownBy(() -> service.get(id)).isInstanceOf(MediaException.class)
                    .hasFieldOrPropertyWithValue("reason", MediaException.Reason.PHOTO_TIMEOUT);
            assertThat(cancelled.await(1, TimeUnit.SECONDS)).isTrue();
            verify(discovery).find(any(), any());
        }
    }

    @Test void catalogOnlyModeDoesNotAccidentallyActivateTheProviderChain() {
        var places = mock(MediaPlaceReader.class); var catalog = mock(MediaCatalog.class); var discovery = mock(PhotoDiscovery.class);
        var id = UUID.randomUUID(); var identity = new OsmIdentity("node", 42);
        when(places.identity(id)).thenReturn(identity); when(catalog.find(identity)).thenReturn(Optional.empty());
        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            assertThat(new MediaService(places, catalog, discovery, executor, Duration.ofSeconds(1), false)
                    .get(id).photos()).isEmpty();
            verifyNoInteractions(discovery);
        }
    }
}
