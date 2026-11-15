# Landmark-media backend review handoff

Prepared for Murat, Daniil and Mukhamed. The feature is submitted on feat/landmark-media
for draft review; deployment and teammate approval remain pending. This note accompanies the existing
[media contract](LANDMARK_PHOTOS_CONTRACT.md), not a competing wire specification.

## What consumers need to know

1. **Opt-in:** API_MEDIA_ENABLED=true exposes GET /api/places/{placeId}/media.
   Default false protects the current MVP release; 404 while disabled is expected.
   Configure this only on the feature test instance, not implicitly on the MVP instance.
2. **Wire fields unchanged:** placeId, status, fetchedAt, placeDescription and photos.
   ready has exactly one photo; empty has none. Nullable description/geotag fields
   remain present. Unknown query parameters, including cache-busters, return 400.
3. **Observed host clarification:** Commons returns thumbnails from
   **thumb.wikimedia.org** as well as upload.wikimedia.org. Full originals remain on
   upload.wikimedia.org. Daniil should include both exact hosts in any thumbnail CSP/
   allowlist. No wildcard or untrusted image host is admitted.
4. **URL normalization:** remove only Commons' observed utm_source/utm_campaign/
   utm_content analytics parameters. Other image query tokens are rejected. Preserve
   the actual file page and license reference; a license URL with/without a trailing
   slash retains its original designation. Observed HTTP Creative Commons references
   are upgraded only to the same HTTPS resource, not relabelled as a newer license.
5. **Limits selected by Murat:** 12-second maximum total lookup, shared Nominatim
   Valkey gate, positive metadata TTL 24 hours and empty TTL five minutes. Queue/
   quota/HTTP/cache work consumes the budget; errors remain errors, not fake empty
   results. Frontend must isolate gallery errors and keep canonical place information.
6. **No changes to agent/route integration:** canonical Place UUIDs are resolved by
   Java to stored OSM identities; legacy Photo/chat/Route shapes, route POST behavior,
   routing cache, schema and agent internals are unchanged. No extra chat field,
   callback, upload or route creation is required for a gallery.
7. **Metadata namespace:** trego:media:commons:v1 is independent of route/research/
   session caches. Only the existing Nominatim gate is shared. Mukhamed should review
   exact gate URL normalization/token/cooldown compatibility; no agent patch is needed.

## Ready for local review, not final demo certification

Five source-linked catalog records cover Strbske Pleso, Skok, Popradske pleso,
Bratislava Castle and St. Martin's Cathedral by exact OSM identity. Metadata and image
connectivity were checked; owners must still review associations/credits and complete
the photo UI scenario. The prior Bratislava text-discovery gap is separate from media;
manual routing is an explicit alternative demo entry mode, not a hidden agent fallback.

Media responses contain plain sourced English Wikidata descriptions when available,
not newly generated tourist text. Photo captions retain their source language. Empty
photos do not erase independent information. A manually created Place without a
verified OSM identity has no photo lookup and keeps its existing name/tags/source.

Review code through api/MEDIA.md. Before enabling jointly, agree the current contract,
review the curated assets and test automatic uncatalogued lookup, empty/manual cards,
full-size viewer/attribution, repeated visits, selection races and dependency failures.
