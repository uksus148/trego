package io.junction.trails.media.cache;

import com.sun.net.httpserver.HttpServer;
import io.junction.trails.media.application.MediaDeadline;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.InetSocketAddress;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.stream.Stream;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import static org.assertj.core.api.Assertions.assertThat;

@Testcontainers
@EnabledIfSystemProperty(named = "agent.python", matches = ".+", disabledReason = "Run with -Dagent.python=<synced agent venv>/bin/python")
class NominatimGateInteropTest {
    @Container static final GenericContainer<?> VALKEY = new GenericContainer<>("valkey/valkey:8.1-alpine").withExposedPorts(6379);
    static LettuceConnectionFactory connections;
    static StringRedisTemplate redis;
    @TempDir Path temporary;

    @BeforeAll static void connect() {
        connections = new LettuceConnectionFactory(VALKEY.getHost(), VALKEY.getMappedPort(6379));
        connections.afterPropertiesSet();
        redis = new StringRedisTemplate(connections);
        redis.afterPropertiesSet();
    }

    @AfterAll static void close() { connections.destroy(); }

    static Stream<Arguments> cases() {
        return Stream.of("https://nominatim.openstreetmap.org", "https://NOMINATIM.openstreetmap.org:443/",
                "http://LOCALHOST:80/nominatim///")
                .flatMap(url -> Stream.of(Arguments.of(url, true), Arguments.of(url, false)));
    }

    @ParameterizedTest @MethodSource("cases")
    void actualJavaAndPythonProvidersNeverOverlapAndKeepCompletionCooldown(String configured, boolean pythonFirst) throws Exception {
        var events = new ConcurrentHashMap<String, Long>();
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", exchange -> {
            events.put(exchange.getRequestURI().getPath().substring(1), System.nanoTime());
            exchange.sendResponseHeaders(200, -1);
            exchange.close();
        });
        server.start();
        Path go = temporary.resolve("go");
        var peer = new ProcessBuilder(System.getProperty("agent.python"), "src/test/python/nominatim_gate_peer.py",
                "--redis-url", "redis://" + VALKEY.getHost() + ":" + VALKEY.getMappedPort(6379),
                "--events", "http://127.0.0.1:" + server.getAddress().getPort(),
                "--url", configured, "--vectors", "src/test/resources/media/nominatim-gate-vectors.json",
                "--go", go.toString(), "--query", UUID.randomUUID().toString());
        peer.environment().put("PYTHONPATH", Path.of("../agent/src").toAbsolutePath().normalize().toString());
        peer.redirectError(temporary.resolve("python.log").toFile());
        Process process = peer.start();
        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            var reader = new BufferedReader(new InputStreamReader(process.getInputStream()));
            String ready = CompletableFuture.supplyAsync(() -> {
                try { return reader.readLine(); } catch (java.io.IOException exception) { throw new java.io.UncheckedIOException(exception); }
            }, executor).get(10, TimeUnit.SECONDS);
            assertThat(ready).withFailMessage(() -> readLog(temporary.resolve("python.log"))).isEqualTo("READY");
            var gate = new NominatimGate(redis, NominatimGateKeyTest.properties(configured).nominatimBaseUrl());
            if (pythonFirst) { Files.createFile(go); waitFor(events, "python-start"); }
            var javaCall = executor.submit(() -> gate.call(new MediaDeadline(Duration.ofSeconds(10)), () -> {
                events.put("java-start", System.nanoTime());
                try { Thread.sleep(400); } catch (InterruptedException exception) { throw new IllegalStateException(exception); }
                events.put("java-end", System.nanoTime());
                return "ok";
            }));
            if (!pythonFirst) { waitFor(events, "java-start"); Files.createFile(go); }
            assertThat(javaCall.get(12, TimeUnit.SECONDS)).isEqualTo("ok");
            assertThat(process.waitFor(12, TimeUnit.SECONDS)).isTrue();
            assertThat(process.exitValue()).withFailMessage(() -> readLog(temporary.resolve("python.log"))).isZero();
            String first = pythonFirst ? "python" : "java", second = pythonFirst ? "java" : "python";
            assertThat(events).containsKeys(first + "-end", second + "-start");
            Duration gap = Duration.ofNanos(events.get(second + "-start") - events.get(first + "-end"));
            System.out.printf("Nominatim interop url=%s first=%s completionGapMs=%d%n", configured, first, gap.toMillis());
            assertThat(gap)
                    .isGreaterThanOrEqualTo(Duration.ofMillis(950));
        } finally {
            process.destroyForcibly();
            server.stop(0);
        }
    }

    private static void waitFor(ConcurrentHashMap<String, Long> events, String name) throws InterruptedException {
        long until = System.nanoTime() + Duration.ofSeconds(5).toNanos();
        while (!events.containsKey(name) && System.nanoTime() < until) { Thread.sleep(10); }
        assertThat(events).containsKey(name);
    }

    private static String readLog(Path path) {
        try { return Files.readString(path); } catch (java.io.IOException exception) { return exception.getClass().getSimpleName(); }
    }
}
