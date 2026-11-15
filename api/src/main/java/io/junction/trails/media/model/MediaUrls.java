package io.junction.trails.media.model;

import java.net.URI;
import java.util.Set;
import java.util.regex.Pattern;

public final class MediaUrls {
    private static final Set<String> REFERENCES = Set.of("commons.wikimedia.org", "www.wikidata.org",
            "www.openstreetmap.org", "creativecommons.org");
    private static final Pattern CC = Pattern.compile("CC (BY|BY-SA) (2\\.0|2\\.5|3\\.0|4\\.0)(?: ([A-Z]{2}))?");

    private MediaUrls() { }

    public static URI image(String value) {
        return onHost(value, Set.of("upload.wikimedia.org"));
    }

    public static URI thumbnail(String value) {
        return onHost(value, Set.of("upload.wikimedia.org", "thumb.wikimedia.org"));
    }

    public static URI commonsPage(String value) {
        URI uri = onHost(value, Set.of("commons.wikimedia.org"));
        if (!uri.getPath().startsWith("/wiki/File:") || uri.getPath().length() <= 11) {
            throw new IllegalArgumentException("Expected a Commons file page");
        }
        return uri;
    }

    public static URI reference(String value) {
        return onHost(value, REFERENCES);
    }

    public static boolean license(String label, String value) {
        if (label == null || value == null) { return false; }
        try {
            URI url = reference(value);
            String licensePath = url.getPath().replaceAll("/+$", "");
            if ("CC0".equals(label)) {
                return "creativecommons.org".equals(url.getHost()) && "/publicdomain/zero/1.0".equals(licensePath);
            }
            if ("Public domain".equals(label)) {
                return ("creativecommons.org".equals(url.getHost()) && "/publicdomain/mark/1.0".equals(licensePath))
                        || ("commons.wikimedia.org".equals(url.getHost()) && "/wiki/Commons:Public_domain".equals(url.getPath()));
            }
            var match = CC.matcher(label);
            if (!match.matches() || !"creativecommons.org".equals(url.getHost())) { return false; }
            String path = "/licenses/" + match.group(1).toLowerCase(java.util.Locale.ROOT) + "/" + match.group(2) + "/";
            if (match.group(3) != null) { path += match.group(3).toLowerCase(java.util.Locale.ROOT) + "/"; }
            return path.replaceAll("/+$", "").equals(licensePath);
        } catch (IllegalArgumentException exception) {
            return false;
        }
    }

    private static URI onHost(String value, Set<String> hosts) {
        if (value == null) { throw new IllegalArgumentException("Missing media URL"); }
        URI uri = URI.create(value);
        if (!"https".equals(uri.getScheme()) || !hosts.contains(uri.getHost()) || uri.getRawUserInfo() != null
                || uri.getPort() != -1 || uri.getRawQuery() != null || uri.getRawFragment() != null
                || uri.getPath().chars().anyMatch(Character::isISOControl)) {
            throw new IllegalArgumentException("Unsafe media URL");
        }
        return uri;
    }
}
