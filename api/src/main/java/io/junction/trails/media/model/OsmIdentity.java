package io.junction.trails.media.model;

public record OsmIdentity(String type, long id) {
    public OsmIdentity {
        if (!("node".equals(type) || "way".equals(type) || "relation".equals(type)) || id <= 0) {
            throw new IllegalArgumentException("Invalid OSM identity");
        }
    }

    public String lookupId() {
        return switch (type) { case "node" -> "N"; case "way" -> "W"; default -> "R"; } + id;
    }
}
