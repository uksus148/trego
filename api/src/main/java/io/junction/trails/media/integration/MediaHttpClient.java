package io.junction.trails.media.integration;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.junction.trails.media.application.MediaDeadline;
import io.junction.trails.media.model.MediaException;
import java.io.ByteArrayOutputStream;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Flow;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import lombok.RequiredArgsConstructor;

@RequiredArgsConstructor
public class MediaHttpClient {
    private final HttpClient client;
    private final ObjectMapper json;
    private final String userAgent;

    public JsonNode get(URI endpoint, Map<String, String> query, MediaDeadline deadline) {
        Duration remaining = deadline.remaining();
        String params = query.entrySet().stream().sorted(Map.Entry.comparingByKey())
                .map(e -> encode(e.getKey()) + "=" + encode(e.getValue())).collect(java.util.stream.Collectors.joining("&"));
        var request = HttpRequest.newBuilder(URI.create(endpoint + "?" + params)).GET()
                .timeout(remaining).header("User-Agent", userAgent).header("Accept", "application/json").build();
        var future = client.sendAsync(request, ignored -> new LimitedBody());
        try {
            var response = future.get(deadline.remaining().toNanos(), TimeUnit.NANOSECONDS);
            deadline.remaining();
            if (response.statusCode() != 200) { throw providerError(); }
            JsonNode body = json.readTree(response.body());
            if (body == null || body.has("error")) { throw providerError(); }
            return body;
        } catch (TimeoutException exception) {
            future.cancel(true);
            throw new MediaException(MediaException.Reason.PHOTO_TIMEOUT);
        } catch (InterruptedException exception) {
            future.cancel(true);
            Thread.currentThread().interrupt();
            throw new MediaException(MediaException.Reason.PHOTO_TIMEOUT);
        } catch (ExecutionException exception) {
            if (exception.getCause() instanceof java.net.http.HttpTimeoutException) {
                throw new MediaException(MediaException.Reason.PHOTO_TIMEOUT);
            }
            throw providerError();
        } catch (java.io.IOException exception) {
            throw providerError();
        } finally {
            if (!future.isDone()) { future.cancel(true); }
        }
    }

    private static String encode(String value) {
        return URLEncoder.encode(value, StandardCharsets.UTF_8);
    }

    private static MediaException providerError() {
        return new MediaException(MediaException.Reason.PHOTO_PROVIDER_ERROR);
    }

    private static final class LimitedBody implements HttpResponse.BodySubscriber<byte[]> {
        private static final int MAX_BYTES = 1_048_576;
        private final CompletableFuture<byte[]> body = new CompletableFuture<>();
        private final ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        private Flow.Subscription subscription;

        @Override public CompletionStage<byte[]> getBody() { return body; }
        @Override public void onSubscribe(Flow.Subscription value) { subscription = value; value.request(1); }
        @Override public void onNext(List<ByteBuffer> buffers) {
            for (ByteBuffer buffer : buffers) {
                if (buffer.remaining() > MAX_BYTES - bytes.size()) {
                    subscription.cancel();
                    body.completeExceptionally(new java.io.IOException("Media response exceeds size limit"));
                    return;
                }
                byte[] chunk = new byte[buffer.remaining()];
                buffer.get(chunk);
                bytes.writeBytes(chunk);
            }
            subscription.request(1);
        }
        @Override public void onError(Throwable error) { body.completeExceptionally(error); }
        @Override public void onComplete() { body.complete(bytes.toByteArray()); }
    }
}
