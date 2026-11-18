# Agent development

Follow [team decisions](../CLAUDE.md) and the [shared contract](../docs/AGENT_API_HANDOFF.md).
These instructions apply to the Python agent and its local lab in
`devtools/agent_lab/`.

- Keep draft updates, clarification and future place verification in the core.
  The lab assembles HTTP and dependencies, provides temporary storage and exposes
  opt-in diagnostics. It uses the same walking handler as other v2 callers.
- Carry the original qualified phrase separately from the model's proposed name
  until independent identity verification. A clarification updates only its
  pending field in its own session. Preserve stop order and repeats. When the
  stop limit is exceeded, ask for a shorter route before accepting a draft.
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
- In agent-v2 PRs, record the tested commit, commands, mode, substitutions,
  real checks and skips. Request review from both @uksus148 and @nnatthebest.
