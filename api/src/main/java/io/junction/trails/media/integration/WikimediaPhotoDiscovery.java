package io.junction.trails.media.integration;

import com.fasterxml.jackson.databind.JsonNode;
import io.junction.trails.media.application.MediaDeadline;
import io.junction.trails.media.application.PhotoDiscovery;
import io.junction.trails.media.cache.NominatimGate;
import io.junction.trails.media.model.MediaException;
import io.junction.trails.media.model.MediaMetadata;
import io.junction.trails.media.model.MediaMetadata.LandmarkPhoto;
import io.junction.trails.media.model.MediaMetadata.SourcedText;
import io.junction.trails.media.model.OsmIdentity;
import java.net.URI;
import java.time.Clock;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import org.jsoup.Jsoup;

@RequiredArgsConstructor
public class WikimediaPhotoDiscovery implements PhotoDiscovery {
    private final MediaHttpClient http;
    private final NominatimGate gate;
    private final MediaProperties properties;
    private final Clock clock;

    @Override
    public MediaMetadata find(OsmIdentity identity, MediaDeadline deadline) {
        URI lookup = URI.create(properties.nominatimBaseUrl().toString().replaceAll("/+$", "") + "/lookup");
        JsonNode osm = gate.call(deadline, () -> http.get(lookup,
                Map.of("osm_ids", identity.lookupId(), "format", "jsonv2", "extratags", "1"), deadline));
        if (!osm.isArray() || osm.size() > 1) { throw providerError(); }
        if (osm.isEmpty()) { return empty(null); }
        JsonNode found = osm.get(0);
        if (!identity.type().equals(found.path("osm_type").asText()) || !found.path("osm_id").isIntegralNumber()
                || !found.path("osm_id").canConvertToLong() || identity.id() != found.path("osm_id").longValue()) {
            throw providerError();
        }
        String qid = found.path("extratags").path("wikidata").asText("");
        if (!qid.matches("Q[1-9][0-9]{0,18}")) { return empty(null); }
        JsonNode wikidata = http.get(properties.wikidataUrl(), Map.of("action", "wbgetentities", "format", "json",
                "ids", qid, "props", "claims|descriptions", "languages", "en"), deadline);
        JsonNode entity = wikidata.path("entities").path(qid);
        if (!entity.isObject()) { throw providerError(); }
        if (entity.has("missing")) { return empty(null); }
        if (!qid.equals(entity.path("id").asText())) { throw providerError(); }
        String entityUrl = "https://www.wikidata.org/wiki/" + qid;
        SourcedText description = description(entity.path("descriptions").path("en").path("value").asText(""), entityUrl);
        List<String> files = imageClaims(entity.path("claims"));
        if (files.isEmpty()) { return empty(description); }
        JsonNode commons = http.get(properties.commonsUrl(), Map.of("action", "query", "format", "json",
                "titles", String.join("|", files), "redirects", "1", "prop", "imageinfo",
                "iiprop", "url|mime|extmetadata", "iiurlwidth", "640"), deadline);
        JsonNode pages = commons.path("query").path("pages");
        if (!pages.isObject()) { throw providerError(); }
        Set<String> titles = resolvedTitles(files, commons.path("query"));
        var photos = new ArrayList<LandmarkPhoto>();
        for (JsonNode page : pages) {
            if (page.has("missing")) { continue; }
            if (!titles.contains(page.path("title").asText())) { throw providerError(); }
            parsePhoto(page, entityUrl).ifPresent(photos::add);
        }
        deadline.remaining();
        photos.sort(Comparator.comparingLong(p -> Long.parseLong(p.id().substring("commons:".length()))));
        return new MediaMetadata(clock.instant(), description, photos.stream().limit(1).toList());
    }

    private MediaMetadata empty(SourcedText description) {
        return new MediaMetadata(clock.instant(), description, List.of());
    }

    private static List<String> imageClaims(JsonNode claims) {
        if (!claims.isObject()) { throw providerError(); }
        JsonNode images = claims.path("P18");
        if (images.isMissingNode()) { return List.of(); }
        if (!images.isArray()) { throw providerError(); }
        boolean preferred = false;
        for (JsonNode claim : images) { preferred |= "preferred".equals(claim.path("rank").asText()); }
        var files = new java.util.TreeSet<String>();
        for (JsonNode claim : images) {
            String rank = claim.path("rank").asText();
            if (!("preferred".equals(rank) || (!preferred && "normal".equals(rank)))) { continue; }
            JsonNode snak = claim.path("mainsnak");
            JsonNode value = snak.path("datavalue").path("value");
            if (!"value".equals(snak.path("snaktype").asText()) || !"commonsMedia".equals(snak.path("datatype").asText())
                    || !value.isTextual()) { continue; }
            String name = value.textValue().strip().replace('_', ' ');
            if (name.isBlank() || name.length() > 250 || name.indexOf('|') >= 0 || name.chars().anyMatch(Character::isISOControl)) { continue; }
            files.add("File:" + name);
        }
        return files.stream().limit(20).toList();
    }

    private static Set<String> resolvedTitles(List<String> files, JsonNode query) {
        var titles = new HashSet<>(files);
        // API title normalization/redirects remain inside Commons; these are not HTTP redirects.
        for (String field : List.of("normalized", "redirects")) {
            JsonNode mappings = query.path(field);
            if (mappings.isMissingNode()) { continue; }
            if (!mappings.isArray() || mappings.size() > 20) { throw providerError(); }
            for (JsonNode mapping : mappings) {
                if (titles.contains(mapping.path("from").asText())) { titles.add(mapping.path("to").asText()); }
            }
        }
        return titles;
    }

    private static java.util.Optional<LandmarkPhoto> parsePhoto(JsonNode page, String entityUrl) {
        try {
            JsonNode id = page.path("pageid");
            if (!id.isIntegralNumber() || !id.canConvertToLong() || id.longValue() <= 0) { return java.util.Optional.empty(); }
            JsonNode info = page.path("imageinfo");
            if (!info.isArray() || info.size() != 1) { return java.util.Optional.empty(); }
            JsonNode image = info.get(0);
            if (!Set.of("image/jpeg", "image/png", "image/webp").contains(image.path("mime").asText())) {
                return java.util.Optional.empty();
            }
            JsonNode meta = image.path("extmetadata");
            String author = plain(meta.path("Artist").path("value").asText());
            if (author.equalsIgnoreCase("Unknown author") || author.equalsIgnoreCase("Unknown")) { return java.util.Optional.empty(); }
            String license = plain(meta.path("LicenseShortName").path("value").asText());
            String licenseUrl = meta.path("LicenseUrl").path("value").asText("");
            if (licenseUrl.startsWith("http://creativecommons.org/")) { licenseUrl = "https" + licenseUrl.substring(4); }
            String source = image.path("descriptionurl").asText("");
            String sourceTitle = io.junction.trails.media.model.MediaUrls.commonsPage(source).getPath().substring("/wiki/".length());
            if (!sourceTitle.replace('_', ' ').equals(page.path("title").asText().replace('_', ' '))) {
                return java.util.Optional.empty();
            }
            String full = imageUrl(image.path("url").asText(""));
            String thumb = image.has("thumburl") ? imageUrl(image.path("thumburl").asText("")) : full;
            var photo = new LandmarkPhoto("commons:" + id.longValue(), "wikimedia_commons", full, thumb,
                    plain(page.path("title").asText()), description(meta.path("ImageDescription").path("value").asText(""), source),
                    author, license, licenseUrl, source, entityUrl, null);
            return java.util.Optional.of(photo);
        } catch (IllegalArgumentException exception) {
            // A rejected candidate is not repaired with invented author/license/coordinates.
            return java.util.Optional.empty();
        }
    }

    private static SourcedText description(String value, String source) {
        String text = plain(value);
        if (text.isBlank()) { return null; }
        if (text.length() > 1000) {
            int end = Character.isHighSurrogate(text.charAt(999)) ? 999 : 1000;
            text = text.substring(0, end);
        }
        return new SourcedText(text, source);
    }

    private static String plain(String value) {
        var document = Jsoup.parse(value);
        document.select("script,style").remove();
        return document.text().strip();
    }

    private static String imageUrl(String value) {
        URI uri = URI.create(value);
        if (uri.getRawQuery() != null) {
            // Commons imageinfo adds these analytics parameters; they do not identify the file.
            for (String parameter : uri.getRawQuery().split("&")) {
                String key = parameter.split("=", 2)[0];
                if (!Set.of("utm_source", "utm_campaign", "utm_content").contains(key)) {
                    throw new IllegalArgumentException("Unexpected image query parameter");
                }
            }
            value = value.substring(0, value.indexOf('?'));
        }
        return value;
    }

    private static MediaException providerError() {
        return new MediaException(MediaException.Reason.PHOTO_PROVIDER_ERROR);
    }
}
