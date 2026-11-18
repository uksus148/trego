# Agent architecture

The Python agent interprets requests and verifies places. Java owns canonical
places, saved routes and routing. The frontend owns the chat and map experience.
The [team decisions](../CLAUDE.md) and [shared handoff contract](../docs/AGENT_API_HANDOFF.md)
govern the public boundary. [PR #92](https://github.com/uksus148/trego./pull/92)
owns the shared documentation reorganization and preserves the handoff link.

## Module map

- [v2/main.py](src/trego_agent/v2/main.py), [config.py](src/trego_agent/v2/config.py)
  and [models.py](src/trego_agent/v2/models.py) define the HTTP factory, deadline,
  and request/response validation. [chat.py](src/trego_agent/v2/chat.py) defines
  the chat interface and the labelled foundation fixture.
- [v2/llm.py](src/trego_agent/v2/llm.py) calls Groq through the existing adapter.
  [route_intent.py](src/trego_agent/v2/route_intent.py) extracts a proposed action
  and checks that each original place phrase appears in the current user text.
- [walk_chat.py](src/trego_agent/v2/walk_chat.py) owns the session draft, allowed
  updates and localized clarification. It receives a draft store and can expose
  draft snapshots to an optional inspector.
- [diagnostics.py](src/trego_agent/v2/diagnostics.py) logs timed stages and safe
  error metadata. The [local lab](../devtools/agent_lab/app.py) assembles HTTP
  and dependencies, supplies [temporary memory](../devtools/agent_lab/drafts.py)
  and displays opt-in, redacted stage details.
- [Legacy discovery](src/trego_agent/discovery.py) and the existing
  [agent entrypoint](src/trego_agent/main.py) still serve the existing pipeline.

## Identity and write rules to preserve

- Keep the original phrase including qualifiers, for example “аэропорта Милана”,
  alongside the model's `proposed_name`. Neither field alone verifies a place.
  The model can select an incomplete verbatim phrase, so realistic multilingual
  requests are a separate check on extraction quality.
- A clarification can fill only the pending endpoint in the same session.
  Keep intermediate visits in order, including repeats. If the model reports
  more than five walking stops, ask for a shorter route before updating the draft.
- Before any future write, verify the requested entity using independent
  geographic evidence, context and OSM identity. Treat ambiguity as a question.
  `descriptiveTargets` and provider choice cannot waive verification. Route
  handoff uses canonical Java UUIDs and preserves stop order and repeats.
- Keep user text and credentials out of normal logs. Detailed inspection belongs
  to an explicit local run.

## Replacement direction and sequence

**Implemented.** Isolated v2 HTTP foundation, local lab, Groq structured output,
walking drafts and endpoint clarification. The lab stores at most 20 drafts
until reset or shutdown. The core returns a question or acknowledges the draft.
There are no researched places or saved routes in this slice.

**Next.** Define the discovery input from the draft, then add bounded search and
geocoding behind replaceable adapters. Check city versus airport, real aliases,
same-name candidates and provider failures before connecting Java. Agree any
public or shared changes with the affected owners. Durable conversation state,
route edits and city tours are later slices.

## History, not current acceptance

See [#78's final review](https://github.com/uksus148/trego./pull/78#pullrequestreview-5909280030)
for historical identity evidence and its limits. [README.md](README.md) covers
setup and launch, [VERIFY.md](VERIFY.md) covers checks, and PRs record results
against the tested commit.
