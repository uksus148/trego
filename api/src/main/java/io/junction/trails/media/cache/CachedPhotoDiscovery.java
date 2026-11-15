package io.junction.trails.media.cache;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.junction.trails.media.application.MediaDeadline;
import io.junction.trails.media.application.PhotoDiscovery;
import io.junction.trails.media.model.MediaException;
import io.junction.trails.media.model.MediaMetadata;
import io.junction.trails.media.model.OsmIdentity;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.util.HexFormat;
import lombok.RequiredArgsConstructor;
import org.springframework.dao.DataAccessException;
import org.springframework.data.redis.core.StringRedisTemplate;

@RequiredArgsConstructor
public class CachedPhotoDiscovery implements PhotoDiscovery {
    public static final String PREFIX = "trego:media:commons:v1:";
    private final StringRedisTemplate redis;
    private final ObjectMapper json;
    private final PhotoDiscovery delegate;
    private final String providerFingerprint;

    @Override
    public MediaMetadata find(OsmIdentity identity, MediaDeadline deadline) {
        String key = key(identity);
        try {
            deadline.remaining();
            String cached = redis.opsForValue().get(key);
            if (cached != null) {
                try {
                    if (cached.length() > 65536) { throw new IllegalArgumentException("Oversized media cache"); }
                    MediaMetadata result = json.readerFor(MediaMetadata.class)
                            .with(DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES,
                                    DeserializationFeature.FAIL_ON_TRAILING_TOKENS, DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                            .readValue(cached);
                    if (result == null) { throw new IllegalArgumentException("Null media cache"); }
                    deadline.remaining();
                    return result;
                } catch (java.io.IOException | IllegalArgumentException exception) {
                    redis.delete(key);
                }
            }
            MediaMetadata result = delegate.find(identity, deadline);
            deadline.remaining();
            redis.opsForValue().set(key, json.writeValueAsString(result),
                    result.photos().isEmpty() ? Duration.ofMinutes(5) : Duration.ofHours(24));
            deadline.remaining();
            return result;
        } catch (DataAccessException exception) {
            throw new MediaException(MediaException.Reason.CACHE_UNAVAILABLE);
        } catch (com.fasterxml.jackson.core.JsonProcessingException exception) {
            throw new IllegalStateException("Cannot serialize media metadata", exception);
        }
    }

    private String key(OsmIdentity identity) {
        try {
            byte[] bytes = (providerFingerprint + "|" + identity.type() + "|" + identity.id()).getBytes(StandardCharsets.UTF_8);
            return PREFIX + HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException(exception);
        }
    }
}
