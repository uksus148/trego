# Agent development

Follow [team decisions](../CLAUDE.md) and the [shared contract](../docs/AGENT_API_HANDOFF.md).
These instructions apply to the Python agent and its local lab in
`devtools/agent_lab/`.

- Inject models through `StructuredModel`. Exercise the real core with a
  substitute model or its HTTP transport. Test output shape separately from
  valid actions and from geographic identity.
- Implement new scenarios in v2 first. Keep dialogue decisions, draft updates,
  and place verification in the core. The lab calls the same handler and owns
  launch, connection selection, temporary storage and opt-in stage inspection.
- Carry the original qualified phrase separately from the model's proposed name
  until independent identity verification. A clarification updates only its
  pending field in its own session. Preserve stop order and repeats. When the
  stop limit is exceeded, ask for a shorter route before accepting a draft.
- Before connecting Java, add discovery regressions with varied names and
  contexts: city-for-airport substitution, evidenced aliases, ambiguous
  candidates that require a question, provider failures, and stop order and
  repeats after resolution. Keep test-specific branches out of runtime code.
- Use the existing stack and directories: runtime in `agent/src/`, core
  tests in `agent/tests/`, lab tests in `devtools/tests/`, and shared
  scenarios in `tests/integration/`. Allow fixed responses only in tests
  and clearly labelled diagnostics. Require an explicit selection for real
  calls and surface provider errors without substituting a fixed result.
- Block external network in regular tests. Keep real application logic in
  regressions and substitute external services at their boundaries. Live
  provider checks are explicit and use personal credentials. Disposable
  loopback services may be enabled explicitly for integration tests.
- Use fresh multilingual inputs when evaluating model understanding. Record
  losses of qualifiers, wrong actions, missing stops and other mismatches,
  with reviewed examples that contain no private information.
- Keep the architecture notebook short. Put setup and launch in README,
  verification procedures in VERIFY, and run results in the PR. Check links
  and usage before deletion. Preserve lockfiles and coordinate common docs
  with [PR #92](https://github.com/uksus148/trego./pull/92).
- Check these boundaries before each v2 PR and add targeted regressions for
  concrete failures. Link to the tests from VERIFY when it helps reproduction.
  Record the tested commit, commands, verified behavior, substitutions,
  actual runs and gaps in the PR. Request review from both @uksus148 and
  @nnatthebest.
