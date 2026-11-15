package io.junction.trails.media.application;

import io.junction.trails.media.catalog.MediaCatalog;
import io.junction.trails.media.model.MediaException;
import io.junction.trails.media.model.MediaMetadata;
import io.junction.trails.media.model.MediaResponse;
import io.junction.trails.media.persistence.MediaPlaceReader;
import java.time.Duration;
import java.util.UUID;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import lombok.RequiredArgsConstructor;

@RequiredArgsConstructor
public class MediaService {
    private final MediaPlaceReader places;
    private final MediaCatalog catalog;
    private final PhotoDiscovery discovery;
    private final ExecutorService executor;
    private final Duration timeout;
    private final boolean autoDiscovery;
    private final Semaphore concurrentLookups = new Semaphore(4);

    public MediaResponse get(UUID id) {
        var deadline = new MediaDeadline(timeout);
        var future = executor.submit(() -> lookup(id, deadline));
        try {
            return future.get(deadline.remaining().toNanos(), TimeUnit.NANOSECONDS);
        } catch (TimeoutException exception) {
            throw new MediaException(MediaException.Reason.PHOTO_TIMEOUT);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new MediaException(MediaException.Reason.PHOTO_TIMEOUT);
        } catch (ExecutionException exception) {
            if (exception.getCause() instanceof RuntimeException runtime) { throw runtime; }
            throw new IllegalStateException("Unexpected media lookup failure", exception.getCause());
        } finally {
            // Interrupt pending rate waits/HTTP futures; never schedule a retry after the caller leaves.
            if (!future.isDone()) { future.cancel(true); }
        }
    }

    private MediaResponse lookup(UUID id, MediaDeadline deadline) {
        boolean acquired = false;
        try {
            if (!concurrentLookups.tryAcquire(deadline.remaining().toNanos(), TimeUnit.NANOSECONDS)) {
                throw new MediaException(MediaException.Reason.PHOTO_TIMEOUT);
            }
            acquired = true;
            var identity = places.identity(id);
            deadline.remaining();
            MediaMetadata metadata;
            if (identity == null) { metadata = MediaMetadata.empty(); }
            else {
                metadata = catalog.find(identity).orElseGet(() -> autoDiscovery
                        ? discovery.find(identity, deadline) : MediaMetadata.empty());
            }
            deadline.remaining();
            return MediaResponse.of(id, metadata);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new MediaException(MediaException.Reason.PHOTO_TIMEOUT);
        } finally {
            if (acquired) { concurrentLookups.release(); }
        }
    }
}
