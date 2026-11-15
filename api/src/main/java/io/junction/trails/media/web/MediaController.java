package io.junction.trails.media.web;

import io.junction.trails.media.application.MediaService;
import io.junction.trails.media.model.MediaException;
import io.junction.trails.media.model.MediaResponse;
import java.util.Map;
import java.util.UUID;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@ConditionalOnProperty(name = "media.enabled", havingValue = "true")
@RequiredArgsConstructor
class MediaController {
    private final MediaService media;

    @GetMapping("/api/places/{placeId}/media")
    MediaResponse get(@PathVariable UUID placeId, @RequestParam Map<String, String> parameters) {
        if (!parameters.isEmpty()) { throw new MediaException(MediaException.Reason.INVALID_REQUEST); }
        return media.get(placeId);
    }
}
