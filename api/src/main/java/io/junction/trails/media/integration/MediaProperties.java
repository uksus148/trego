package io.junction.trails.media.integration;

import java.net.URI;
import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

@ConfigurationProperties("media")
public record MediaProperties(
        @DefaultValue("https://nominatim.openstreetmap.org") URI nominatimBaseUrl,
        @DefaultValue("https://www.wikidata.org/w/api.php") URI wikidataUrl,
        @DefaultValue("https://commons.wikimedia.org/w/api.php") URI commonsUrl,
        @DefaultValue("trego/0.1 (contact: https://github.com/uksus148/trego./issues)") String userAgent,
        @DefaultValue("12s") Duration lookupTimeout,
        @DefaultValue("2s") Duration connectTimeout,
        @DefaultValue("classpath:media/catalog.json") String catalog,
        @DefaultValue("true") boolean autoDiscoveryEnabled) {
    public MediaProperties {
        if (lookupTimeout.isZero() || lookupTimeout.isNegative() || lookupTimeout.compareTo(Duration.ofSeconds(12)) > 0
                || connectTimeout.isZero() || connectTimeout.isNegative() || connectTimeout.compareTo(lookupTimeout) > 0
                || userAgent == null || userAgent.isBlank() || userAgent.contains("\r") || userAgent.contains("\n")) {
            throw new IllegalArgumentException("Invalid media timeouts or user agent");
        }
        endpoint(nominatimBaseUrl);
        endpoint(wikidataUrl);
        endpoint(commonsUrl);
    }

    private static void endpoint(URI uri) {
        boolean local = "http".equals(uri.getScheme()) && java.util.Set.of("127.0.0.1", "localhost", "[::1]").contains(uri.getHost());
        if ((!"https".equals(uri.getScheme()) && !local) || uri.getHost() == null
                || uri.getRawUserInfo() != null || uri.getRawQuery() != null || uri.getRawFragment() != null) {
            throw new IllegalArgumentException("Media providers need HTTPS or loopback test endpoints");
        }
    }
}
