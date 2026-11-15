package io.junction.trails.media.application;

import io.junction.trails.media.model.MediaException;
import java.time.Duration;

public final class MediaDeadline {
    private final long expires;

    public MediaDeadline(Duration budget) {
        expires = System.nanoTime() + budget.toNanos();
    }

    public Duration remaining() {
        long nanos = expires - System.nanoTime();
        if (nanos <= 0 || Thread.currentThread().isInterrupted()) {
            throw new MediaException(MediaException.Reason.PHOTO_TIMEOUT);
        }
        return Duration.ofNanos(nanos);
    }
}
