package io.junction.trails.media.model;

import lombok.Getter;

@Getter
public class MediaException extends RuntimeException {
    private final Reason reason;

    public MediaException(Reason reason) {
        super(reason.detail);
        this.reason = reason;
    }

    public enum Reason {
        INVALID_REQUEST(400, "The place ID or media query parameters are invalid."),
        PLACE_NOT_FOUND(404, "The requested place does not exist."),
        PHOTO_PROVIDER_ERROR(502, "Photo metadata is temporarily unavailable."),
        STORAGE_UNAVAILABLE(503, "Place storage is temporarily unavailable."),
        CACHE_UNAVAILABLE(503, "Photo metadata coordination is unavailable."),
        PHOTO_TIMEOUT(504, "Photo lookup exceeded its deadline.");

        @Getter private final int status;
        private final String detail;

        Reason(int status, String detail) {
            this.status = status;
            this.detail = detail;
        }
    }
}
