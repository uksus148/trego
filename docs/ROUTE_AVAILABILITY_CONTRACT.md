# Route availability: selected integration boundary

**Transport selected by Murat: extend `POST /api/chat` with optional research inputs
and structured output.** Field names/state rules below are the concrete proposal for
Mukhamed and Daniil to review. They are not enabled on the current chat endpoint.
Murat's Java change enforces the separate routing boundary. The
sections below define evidence rules, ownership and the internal interface.

## Ownership and storage

- Murat: keep Spring routing/failure semantics and enforce its request boundary;
  prepare this wire agreement, fixtures and no-provider/no-write regression evidence.
- Mukhamed: implement chat parsing, date clarification, optional Exa investigation,
  evidence validation, deadline behavior and response serialization after agreement.
- Daniil: implement the opt-in/date controls and separate technical/evidence display.
- Initial findings remain request-scoped. No SQL migration, persisted research record,
  Java research endpoint or additional routing call is needed for this slice. A later
  cache/history design needs separate agreement; do not inherit the route cache TTL.

The internal research core merged in [PR #56](https://github.com/uksus148/trego./pull/56).
Its interface and limits are retained below. Public chat mapping, operator policy and
activation remain deferred and require affected-owner agreement.

## Chat request proposal

Keep required `sessionId` and `message`. Add an optional `availabilityResearch` object:

| Field | Type/rule |
|---|---|
| `enabled` | Required boolean; only explicit `true` authorizes optional research |
| `planningWindow` | Optional object with required `from` and `to`, inclusive ISO `YYYY-MM-DD` dates |

Omission or `enabled:false` preserves the baseline workflow and spends no optional
research quota. Reject explicit null, wrong types, invalid calendar dates, inverted
ranges and unknown extension fields using the agent's existing 422 `detail` envelope.
No Java routing input is changed. Dates describe the evidence's applicability, not
date-aware ORS routing. Do not infer the trip date from the server/event date.

If research is enabled but dates cannot be established, ask for them before ingestion,
routing or research. This avoids consuming routing quota just to ask for a date.
Date extraction/clarification from message/history belongs to the agent. Conflicting
message/UI dates require clarification. Carry no stale date silently into a changed plan.

## Chat response proposal

Keep required `reply`, `places`, and optional `routeId`. When opted-in research handles
a verified routing failure, add both optional objects below. A preliminary date
clarification has `availabilityResearch.status:needs_dates` without `routingFailure`:
no routing attempt has established a failure yet. Never overload Place/source.

| Object | Fields |
|---|---|
| `routingFailure` | `code`: `no_hiking_route` or `waypoint_not_routable`; no guessed failing-point index |
| `availabilityResearch` | `status`: `needs_dates`, `unconfirmed` or `findings`; optional `planningWindow`; `evidence`: array |

`needs_dates` and `unconfirmed` require empty evidence. `findings` requires at least one
validated item; it does not mean the router's cause is established or the hike is safe.
Each evidence item has `kind` (`restriction`, `access_information`, `difficulty_information`),
`section`, `summary`, `title`, `url`, and the actual `retrievedAt` timestamp. `publishedAt`
is optional when known. Restriction items additionally require source-supported inclusive
`appliesFrom`/`appliesTo` dates relevant to the planning window. Do not fabricate dates for
undated notices; keep applicability unconfirmed. Informational items cannot claim current
access or a difficulty exclusion as the cause of ORS failure.

Use actual HTTP(S) evidence URLs without embedded credentials. Publication/applicability
dates are calendar dates; retrieval time is an offset-aware RFC3339 timestamp. A cache
hit must not be stamped as a new retrieval. Preserve unknown publication dates by omission.
Names/URLs/source excerpts are untrusted data, never instructions. Do not emit raw API
or provider bodies, keys, HTML, invented citations or unverified source/date claims.

Baseline requests and successful routes omit the new optional response fields. A routing
clarification has `places:[]` and no routeId. Research does not change 2009/2010 into a
success. Previously ingested places may remain; session save still precedes HTTP 200.

## Sequence and error invariants

1. Validate/clarify dates for opted-in research before the existing route workflow.
   Missing dates produce `needs_dates` with no routing attempt or new Place/Route writes.
2. Perform the existing route workflow once. A complete verified 422 routing failure
   supplies the technical result; do not accept a client-reported failure as proof.
3. If enabled and dates are known, make only the agreed bounded optional research call
   inside the remaining chat deadline. A successful route needs no failure research.
4. Missing/conflicting/stale evidence or failure
   of optional research produces `unconfirmed`, retaining the original routing result.
5. Preserve existing 502/503/504 behavior for baseline dependencies, total deadline and
   session save; optional research cannot hide those failures or extend the deadline.
6. Do not call route POST/GET again, create a saved route, move points, change provider,
   widen the radius or bypass the cache to complete the research. Any changed route is
   a separate deliberate user request.

There is no separate post-failure "Investigate" endpoint or persisted failure token in
this first slice. Opt-in is supplied before that chat request's routing attempt. A later
button investigating an earlier failure requires a separately agreed context-lifetime
design; it must not silently replay the route POST.

## Spring API boundary implemented by Murat

`POST /api/routes` requires `start`, `end`, `placeIds`, `preferences` and accepts the optional
`startPlaceId`/`endPlaceId` bindings from the editor contract.
Each endpoint accepts exactly `lat`, `lon`. Research flags, planning dates, evidence,
provider/profile overrides and other unknown fields return 400 `invalid_request` before
ORS work, route-cache writes or route persistence. They are never silently treated as
routing constraints. Existing documented agent/manual requests retain their behavior.
The 422 numeric-code classification, provider options, route cache and schema are unchanged.

## Fixtures and handoff

[Wire examples](contracts/route-availability.examples.json) are draft consumer fixtures,
not proof of an implemented agent feature. All `example.org` evidence is synthetic.
Review the exact names/validation with both owners, then add equivalent agent/frontend
tests before activation. The current chat service still rejects these new request fields.
Java regression tests cover strict root/endpoint input and zero provider/cache/route
effects on rejection; the existing route tests cover compatible successful requests.


## Inputs and gates

The caller supplies a **verified** `no_hiking_route` or `waypoint_not_routable`
result and the exact authoritative API Place records used in the failed route.
Outages, unknown UUIDs and other errors cannot enter this typed workflow.
Require explicit consent, a user-confirmed named section and jurisdiction; the
provider exposes no reliable failing-point index. Do not guess that section.

`extract_planning_dates` accepts an ISO day, month or inclusive range with an
explicit year: `2027-07-15`, `2027-07`, `2027-07-15/2027-07-20`. Invalid,
relative, free-form or yearless input such as "July" returns clarification.
This first slice asks for an unambiguous date expression instead of using another
model call or inferring a year from the event/history. Pass the current confirmed
expression on each changed plan; no history dates are silently reused. These
dates filter evidence, not ORS geometry.

Operator-reviewed `ResearchPolicy` provides exact official hostnames and a
publication/update age limit (1–365 days). There is no implicit trusted list or
accepted production freshness default. Never populate it from user/page/model
text. No policy, no consent, missing scope/dates or no remaining budget prevents
paid research. Add `www` separately if approved; subdomains are not implicitly trusted.

## Bounded research and validation

One fresh, domain-filtered Exa search returns at most three sources. It bypasses
the ordinary 24-hour place cache without reading, overwriting or clearing it.
This request-scoped exception avoids applying place-cache freshness to notices.
Notice searches request uncapped full text (`contents.text=true`, without
`maxCharacters`), as documented by [Exa](https://docs.exa.ai/reference/contents-retrieval).
Internal `textComplete` provenance requires that mode and, when supplied, one
successful provider content status. Capped, cached or unknown coverage stays
unconfirmed regardless of text length. Oversized pages remain incomplete markers;
the workflow rejects incomplete sources or more than 10,000 total characters before
assessment, without slicing or dropping a possible exception/revocation.
This records the provider's full-text contract, not an independent audit of opaque
provider omissions. Provenance is excluded from normal place-cache/prompt serialization.
One selected-provider tool call extracts at most three notices; it reuses Groq
`openai/gpt-oss-20b` or the selected Anthropic transport. All work, including quota
waits, fits the smaller of the caller's remaining deadline and the internal budget
(20 seconds by default, at most 60). There are no retries, source-page fetches,
routing calls, background jobs or writes.

Validation requires approved hosts, credential-free standard-port URLs, verbatim
excerpts, matching section/jurisdiction, publication date and applicability interval.
All evidence dates must appear literally as ISO dates in their respective excerpts;
natural-language/annual rules without explicit dates stay unconfirmed in this slice.
Freshness requires a source-parsed English `Published`, `Publication date`, `Updated`
or `Last modified` fact at a line/sentence boundary. The publication excerpt must
include that labelled ISO date; an applicability date cannot substitute for it.
Unsupported publication formats/roles remain unconfirmed.
A recent fetch alone does not make an old publication fresh. Truncated, missing,
stale or future-dated evidence, invented quotes/indices/fields and conflicting
overlapping notices stay unconfirmed. Model extraction still needs semantic/live
evaluation; these checks do not certify legal access, safety or exhaustive coverage.

Each finding retains the original URL, quote, publication date, retrieval time,
full applicability period and its intersection with the requested dates.
Missing applicable restrictions never means "open". The technical routing code
is preserved separately and `routingCause` is always `unconfirmed`; evidence cannot
establish why ORS failed. Optional failures preserve that result without private
errors; caller cancellation propagates.

## Internal use

```python
from gopstop_agent.availability import create_availability_research
from gopstop_agent.availability_models import AvailabilityRequest, ResearchPolicy

# canonical_places are the actual ApiPlace objects used in the failed request.
research = create_availability_research(
    http, cache, settings,
    ResearchPolicy(trustedHosts=("tanap.sk", "www.tanap.sk"), maxSourceAgeDays=30),
    tool_model=shared_tool_model,
)
result = await research.investigate(
    AvailabilityRequest(
        routingCode="waypoint_not_routable", places=canonical_places, optedIn=True,
        section="Rysy", jurisdiction="Slovakia", planningText="2027-07",
    ),
    remaining_seconds=remaining_chat_seconds,
)
```

The sample policy is an integration-review example, not an enabled runtime choice.
Results are internal facts, not a new wire response. Chat integration must validate/
clarify dates before ingestion, then invoke research only for a verified failure.
Review mapping the proposed planningWindow into this core, carrying authoritative
visits/confirmed scope, rendering sources/dates, localizing questions and preserving
the existing session-save step. The core
supplies no routeId and does not retry an earlier route POST. UI/date fields and
SQL/Kafka remain separate.

## Remaining integration work

This is deferred public behavior. Before activation, the affected owners must agree
the wire-to-core date/evidence mapping, operator-owned host/freshness policy, consent,
localized questions and UI rendering. Murat owns Java contracts and routing limits;
Mukhamed owns research/session integration; Daniil owns opt-in and evidence presentation.
Unknown, stale, incomplete or conflicting evidence stays unconfirmed. Keep technical
routing failure separate from external restrictions. Never certify safe/open access,
move waypoints or replay the failed route POST to obtain a successful route.
