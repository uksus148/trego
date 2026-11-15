package io.junction.trails.media.cache;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.junction.trails.media.application.MediaDeadline;
import io.junction.trails.media.integration.MediaProperties;
import java.net.URI;
import java.time.Duration;
import java.util.Map;
import java.util.stream.Stream;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import org.mockito.ArgumentCaptor;
import org.springframework.boot.context.properties.bind.Bindable;
import org.springframework.boot.context.properties.bind.Binder;
import org.springframework.boot.context.properties.source.MapConfigurationPropertySource;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class NominatimGateKeyTest {
    static JsonNode vectors() throws Exception {
        try (var input = NominatimGateKeyTest.class.getResourceAsStream("/media/nominatim-gate-vectors.json")) {
            return new ObjectMapper().readTree(input);
        }
    }

    static Stream<JsonNode> accepted() throws Exception {
        return java.util.stream.StreamSupport.stream(vectors().path("accepted").spliterator(), false);
    }

    static Stream<String> rejected() throws Exception {
        return java.util.stream.StreamSupport.stream(vectors().path("rejected").spliterator(), false).map(JsonNode::asText);
    }

    static MediaProperties properties(String configured) {
        var source = new MapConfigurationPropertySource(Map.of("media.nominatim-base-url", configured));
        return new Binder(source).bind("media", Bindable.of(MediaProperties.class)).get();
    }

    @ParameterizedTest @MethodSource("accepted")
    @SuppressWarnings("unchecked")
    void productionBindingAndDirectGateMatchSharedPythonVectors(JsonNode vector) {
        String configured = vector.path("configured").asText();
        var properties = properties(configured);
        assertThat(properties.nominatimBaseUrl().toString()).isEqualTo(vector.path("base").asText());
        // Both production binding and direct construction must be safe.
        for (URI uri : new URI[]{properties.nominatimBaseUrl(), URI.create(configured)}) {
            var redis = mock(StringRedisTemplate.class);
            ValueOperations<String, String> values = mock(ValueOperations.class);
            when(redis.opsForValue()).thenReturn(values);
            when(values.setIfAbsent(anyString(), anyString(), any(Duration.class))).thenReturn(true);
            assertThat(new NominatimGate(redis, uri).call(new MediaDeadline(Duration.ofSeconds(2)), () -> "ok")).isEqualTo("ok");
            var key = ArgumentCaptor.forClass(String.class);
            verify(values).setIfAbsent(key.capture(), anyString(), any(Duration.class));
            assertThat(key.getValue()).isEqualTo(vector.path("key").asText());
        }
    }

    @ParameterizedTest @MethodSource("rejected")
    void unsupportedSpellingsFailDuringConfigurationBinding(String configured) {
        assertThatThrownBy(() -> properties(configured)).hasRootCauseInstanceOf(IllegalArgumentException.class);
    }
}
