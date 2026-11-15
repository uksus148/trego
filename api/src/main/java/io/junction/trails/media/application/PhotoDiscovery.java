package io.junction.trails.media.application;

import io.junction.trails.media.model.MediaMetadata;
import io.junction.trails.media.model.OsmIdentity;

public interface PhotoDiscovery {
    MediaMetadata find(OsmIdentity identity, MediaDeadline deadline);
}
