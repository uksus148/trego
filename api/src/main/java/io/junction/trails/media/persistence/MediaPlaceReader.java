package io.junction.trails.media.persistence;

import io.junction.trails.media.model.MediaException;
import io.junction.trails.media.model.OsmIdentity;
import io.junction.trails.places.persistence.PlaceRepository;
import java.util.UUID;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class MediaPlaceReader {
    private final PlaceRepository places;

    @Transactional(readOnly = true)
    public OsmIdentity identity(UUID id) {
        var place = places.findById(id).orElseThrow(() -> new MediaException(MediaException.Reason.PLACE_NOT_FOUND));
        return place.getOsmId() == null ? null : new OsmIdentity(place.getOsmType(), place.getOsmId());
    }
}
