package io.junction.trails.media.cache;

import io.junction.trails.media.application.MediaDeadline;
import io.junction.trails.media.model.MediaException;
import io.junction.trails.media.model.NominatimBaseUrl;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;
import java.util.function.Supplier;
import org.springframework.dao.DataAccessException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;

public class NominatimGate {
    private static final DefaultRedisScript<Long> COOLDOWN = new DefaultRedisScript<>("""
            if redis.call('get', KEYS[1]) == ARGV[1] then
                return redis.call('pexpire', KEYS[1], 1000)
            end
            return 0
            """, Long.class);
    private final StringRedisTemplate redis;
    private final String key;

    public NominatimGate(StringRedisTemplate redis, URI baseUrl) {
        this.redis = redis;
        try {
            // This namespace/hash/token/one-second cooldown exactly matches the agent.
            String base = new NominatimBaseUrl(baseUrl).uri().toString();
            key = "gopstop:nominatim:gate:v1:" + HexFormat.of().formatHex(
                    MessageDigest.getInstance("SHA-256").digest(base.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException(exception);
        }
    }

    public <T> T call(MediaDeadline deadline, Supplier<T> request) {
        String token = UUID.randomUUID().toString();
        boolean acquired = false;
        boolean succeeded = false;
        try {
            Duration lease = deadline.remaining().plusSeconds(2);
            while (!Boolean.TRUE.equals(redis.opsForValue().setIfAbsent(key, token, lease))) {
                long wait = Math.min(50, Math.max(1, deadline.remaining().toMillis()));
                Thread.sleep(wait);
            }
            acquired = true;
            deadline.remaining();
            T result = request.get();
            succeeded = true;
            return result;
        } catch (DataAccessException exception) {
            throw new MediaException(MediaException.Reason.CACHE_UNAVAILABLE);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new MediaException(MediaException.Reason.PHOTO_TIMEOUT);
        } finally {
            if (acquired) {
                try { redis.execute(COOLDOWN, List.of(key), token); }
                catch (DataAccessException exception) {
                    // Preserve an original provider failure, but do not hide coordination failure on success.
                    if (succeeded) { throw new MediaException(MediaException.Reason.CACHE_UNAVAILABLE); }
                }
            }
        }
    }
}
