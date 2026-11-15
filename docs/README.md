# trego. documentation

trego. is a travel navigator for sightseeing and outdoor trips. Current routing is
walking via ORS `foot-hiking`. Broader positioning does not enable driving, cycling,
transit, personalized routing or date-aware availability.

## Start here

- [Project overview and setup](../README.md).
- [Canonical architecture, API contract and owner tasks](../CLAUDE.md).
- [Contribution conventions](../CONTRIBUTING.md) and [repository rules](REPOSITORY_RULES.md).
- [Integration ledger, startup and evidence](INTEGRATION_RUNBOOK.md).
- [Version checkpoints and recovery](RELEASE_BASELINE.md).

## Implemented contracts and guides

| Area | Contract / behavior | Setup / review guide |
|---|---|---|
| Places and researched ingestion | [Accepted API handoff](AGENT_API_HANDOFF.md) | [API](../api/README.md), [ingestion](../api/INGESTION.md) |
| Saved walking routes | [Canonical contract](../CLAUDE.md#api-contract) | [Routing](../api/ROUTES.md), [provider diagnostics](ROUTING_DIAGNOSTICS.md) |
| Landmark information/photos | [Media contract](LANDMARK_PHOTOS_CONTRACT.md) | [Media implementation](../api/MEDIA.md) |
| Route editing | [Editor v1](ROUTE_EDITING_CONTRACT.md), [shared examples](contracts/route-editing.examples.json) | [Java trace/V4](../api/ROUTE_EDITING.md), [frontend](../frontend/README.md) |
| Chat and place identity | [Canonical chat contract](../CLAUDE.md#api-contract) | [Agent](../agent/README.md), [OSM identity](../agent/OSM_IDENTITIES.md), [requested identity](../agent/IDENTITY_REVIEW.md) |
| Local services and delivery | [Infrastructure](../infra/README.md) | [API container](../api/CONTAINER.md), [fixture acceptance](../tests/integration/README.md) |

The real editor and landmark media require explicit activation. Follow the service
guides and deploy the corresponding API/schema before enabling frontend consumers.

## Retained plans and evidence

The [agent delivery record](AGENT_PLAN.md) and [stabilization sequence](AGENT_STABILIZATION_PLAN.md)
preserve diagnostic decisions and still-open live acceptance gates. Earlier test
counts, model results and revision IDs remain historical evidence.

The availability [research plan](ROUTE_AVAILABILITY_RESEARCH_PLAN.md),
[wire proposal](ROUTE_AVAILABILITY_CONTRACT.md) and [internal agent core](../agent/AVAILABILITY.md)
remain useful for deferred work. They do not describe an enabled public feature.
Day planning and personalization remain proposals in CLAUDE.md. Keep these documents
until their owners explicitly supersede the design or close the remaining work.

## Completed handoffs removed for version 3

| Removed file | Why it is redundant | Authoritative replacement |
|---|---|---|
| `CONTRACT_REVIEW.md` | Initial unresolved questions were superseded by accepted contracts; deferred proposals already live in CLAUDE.md | CLAUDE.md, AGENT_API_HANDOFF.md and repository review rules |
| `ROUTE_EDITING_FRONTEND_PROMPT.md` | One-off implementation prompt completed by merged #87; it targeted an older baseline | ROUTE_EDITING_CONTRACT.md, shared examples, component guides and executable tests |
| `LANDMARK_MEDIA_BACKEND_HANDOFF.md` | Draft delivery note completed by #73/#71/#74 | LANDMARK_PHOTOS_CONTRACT.md and api/MEDIA.md, including thumbnail hosts and consumer compatibility notes |

Deletion removes obsolete instructions from the current checkout. Their exact
historical contents remain recoverable through Git and earlier version tags.
Contracts, migrations, recovery instructions and unique diagnostic evidence remain.
