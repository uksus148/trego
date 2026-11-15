package io.junction.trails.media.model;

import java.net.URI;
import java.util.Locale;
import java.util.Set;

/** A bounded URL surface with the same gate identity as the agent's HttpUrl settings. */
public record NominatimBaseUrl(URI uri) {
    public NominatimBaseUrl {
        if (uri == null || uri.getScheme() == null || uri.getHost() == null || uri.getRawUserInfo() != null
                || uri.getRawQuery() != null || uri.getRawFragment() != null) {
            throw new IllegalArgumentException("Nominatim base URL needs a host and no credentials, query or fragment");
        }
        String scheme = uri.getScheme().toLowerCase(Locale.ROOT);
        String host = uri.getHost().toLowerCase(Locale.ROOT);
        boolean local = Set.of("localhost", "127.0.0.1", "[::1]").contains(host);
        if (!(scheme.equals("https") || scheme.equals("http") && local)
                || uri.getPort() > 65535) {
            throw new IllegalArgumentException("Nominatim needs HTTPS or a loopback HTTP fixture URL with a valid port");
        }
        // HttpUrl also rewrites unusual IP literals, escaped paths and dot segments.
        // Reject those spellings rather than guessing a different cross-runtime identity.
        if (host.contains(":") && !host.equals("[::1]")
                || numericHost(host) && !canonicalIpv4(host)) {
            throw new IllegalArgumentException("Nominatim base URL needs a DNS host, canonical IPv4 or [::1]");
        }
        String path = uri.getRawPath();
        if (!path.matches("(?:/[A-Za-z0-9._~-]*)*")
                || java.util.Arrays.stream(path.split("/", -1)).anyMatch(p -> p.equals(".") || p.equals(".."))) {
            throw new IllegalArgumentException("Nominatim path prefix needs plain ASCII segments without escapes or dot segments");
        }
        int port = uri.getPort();
        if (scheme.equals("https") && port == 443 || scheme.equals("http") && port == 80) { port = -1; }
        String base = scheme + "://" + host + (port == -1 ? "" : ":" + port) + path;
        uri = URI.create(base.replaceAll("/+$", ""));
    }

    private static boolean numericHost(String host) {
        String last = host.replaceAll("\\.$", "");
        last = last.substring(last.lastIndexOf('.') + 1);
        return last.matches("[0-9]+|0[xX][0-9a-fA-F]+");
    }

    private static boolean canonicalIpv4(String host) {
        String[] parts = host.split("\\.", -1);
        if (parts.length != 4) { return false; }
        for (String part : parts) {
            if (!part.matches("0|[1-9][0-9]{0,2}") || Integer.parseInt(part) > 255) { return false; }
        }
        return true;
    }
}
