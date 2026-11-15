package io.junction.trails.media.integration;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.junction.trails.media.application.MediaService;
import io.junction.trails.media.application.PhotoDiscovery;
import io.junction.trails.media.cache.CachedPhotoDiscovery;
import io.junction.trails.media.cache.NominatimGate;
import io.junction.trails.media.catalog.MediaCatalog;
import io.junction.trails.media.persistence.MediaPlaceReader;
import java.net.http.HttpClient;
import java.time.Clock;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.io.ResourceLoader;
import org.springframework.data.redis.core.StringRedisTemplate;

@Configuration
@ConditionalOnProperty(name = "media.enabled", havingValue = "true")
@EnableConfigurationProperties(MediaProperties.class)
public class MediaConfiguration {
    @Bean(destroyMethod = "close")
    ExecutorService mediaExecutor() {
        return Executors.newVirtualThreadPerTaskExecutor();
    }

    @Bean
    MediaCatalog mediaCatalog(ObjectMapper json, ResourceLoader resources, MediaProperties properties) {
        return new MediaCatalog(json, resources, properties.catalog());
    }

    @Bean
    PhotoDiscovery photoDiscovery(ObjectMapper json, StringRedisTemplate redis, MediaProperties properties) {
        var client = HttpClient.newBuilder().connectTimeout(properties.connectTimeout())
                .followRedirects(HttpClient.Redirect.NEVER).build();
        var http = new MediaHttpClient(client, json, properties.userAgent());
        var gate = new NominatimGate(redis, properties.nominatimBaseUrl());
        var provider = new WikimediaPhotoDiscovery(http, gate, properties, Clock.systemUTC());
        String fingerprint = properties.nominatimBaseUrl() + "|" + properties.wikidataUrl() + "|" + properties.commonsUrl();
        return new CachedPhotoDiscovery(redis, json, provider, fingerprint);
    }

    @Bean
    MediaService mediaService(MediaPlaceReader places, MediaCatalog catalog, PhotoDiscovery discovery,
                              ExecutorService mediaExecutor, MediaProperties properties) {
        return new MediaService(places, catalog, discovery, mediaExecutor,
                properties.lookupTimeout(), properties.autoDiscoveryEnabled());
    }
}
