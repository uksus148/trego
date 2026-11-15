package io.junction.trails.media.integration;

import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.Executors;

public final class MediaFixtureServer implements AutoCloseable {
    private final HttpServer server;
    private final java.util.concurrent.ExecutorService executor = Executors.newCachedThreadPool();
    private final Map<String, Reply> responses = new ConcurrentHashMap<>();
    public final List<URI> requests = new CopyOnWriteArrayList<>();

    public MediaFixtureServer() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.setExecutor(executor);
        server.createContext("/", exchange -> {
            requests.add(exchange.getRequestURI());
            Reply reply = responses.getOrDefault(exchange.getRequestURI().getPath(), new Reply(500, "{}", 0));
            byte[] bytes = reply.body().getBytes(StandardCharsets.UTF_8);
            try {
                exchange.getResponseHeaders().set("Content-Type", "application/json");
                exchange.sendResponseHeaders(reply.status(), bytes.length);
                exchange.getResponseBody().flush();
                Thread.sleep(reply.delay());
                exchange.getResponseBody().write(bytes);
            } catch (InterruptedException exception) { Thread.currentThread().interrupt(); }
            catch (IOException ignored) { /* A deadline may close the client before the fixture writes. */ }
            finally { exchange.close(); }
        });
        server.start();
        reset();
    }

    public URI base() { return URI.create("http://127.0.0.1:" + server.getAddress().getPort()); }
    public void reply(String path, int status, String body, long delay) { responses.put(path, new Reply(status, body, delay)); }
    public void reset() {
        requests.clear();
        responses.clear();
        reply("/lookup", 200, """
                [{"osm_type":"node","osm_id":42,"extratags":{"wikidata":"Q42"}}]
                """, 0);
        reply("/wikidata", 200, """
                {"entities":{"Q42":{"id":"Q42","descriptions":{"en":{"value":"A fixture waterfall"}},
                "claims":{"P18":[{"rank":"normal","mainsnak":{"snaktype":"value","datatype":"commonsMedia",
                "datavalue":{"value":"Fixture.jpg"}}}]}}}}
                """, 0);
        reply("/commons", 200, commons(), 0);
    }

    public static String commons() {
        return """
                {"query":{"pages":{"123":{"pageid":123,"title":"File:Fixture.jpg","imageinfo":[{
                "url":"https://upload.wikimedia.org/fixture-full.jpg",
                "thumburl":"https://upload.wikimedia.org/fixture-thumb.jpg",
                "descriptionurl":"https://commons.wikimedia.org/wiki/File:Fixture.jpg","mime":"image/jpeg",
                "extmetadata":{"Artist":{"value":"<a href='https://example.org'>Fixture creator</a>"},
                "LicenseShortName":{"value":"CC BY-SA 3.0"},
                "LicenseUrl":{"value":"https://creativecommons.org/licenses/by-sa/3.0/"},
                "ImageDescription":{"value":"<p>A fixture image &amp; caption</p><script>do evil</script>"}}
                }]}}}}
                """;
    }

    @Override public void close() { server.stop(0); executor.shutdownNow(); }
    private record Reply(int status, String body, long delay) { }
}
