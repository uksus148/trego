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

## V2 boundaries

1. **Replaceable model.** [`StructuredModel.complete`](src/trego_agent/v2/llm.py)
   is the model boundary. The extractor validates output shape and quoted user
   text. The conversation handler checks whether the proposed action is allowed.
   Geographic identity needs a separate check. [Tests](VERIFY.md#v2-regressions)
   exercise the real workflow through a substitute model or HTTP transport.
2. **Shared core.** The [lab](../devtools/agent_lab/app.py) launches the same
   walking handler, selects connections, supplies temporary storage and displays
   stages. Implement conversation and place verification in v2 before exposing
   their results in the lab.
3. **Code and evidence.** Runtime code lives in [`agent/src/`](src/).
   Use [`agent/tests/`](tests/), [`devtools/tests/`](../devtools/tests/) and
   [`tests/integration/`](../tests/integration/) for core, lab and shared checks
   respectively. Fixed replies are for tests and labelled diagnostics. Live
   calls require explicit selection. A provider failure surfaces as an error.

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
geocoding behind replaceable adapters. Before connecting Java, prove through the
real core with substituted providers that:

- Identity uses the original qualified phrase and independent evidence. A city
  cannot stand in for its airport. A genuine alias can pass with evidence.
- Multiple plausible matches for the same name trigger clarification. A provider
  failure stays an error. Neither case can reach Java writes.
- Resolved stops retain order and repeats. Use different names and contexts in
  the regressions, with no city-specific test branches in runtime code.

Agree public or shared changes with the affected owners. Durable conversation
state, route edits and city tours are later slices.

## History, not current acceptance

See [#78's final review](https://github.com/uksus148/trego./pull/78#pullrequestreview-5909280030)
for historical identity evidence and its limits. [README.md](README.md) covers
setup and launch, [VERIFY.md](VERIFY.md) covers checks, and PRs record results
against the tested commit.
