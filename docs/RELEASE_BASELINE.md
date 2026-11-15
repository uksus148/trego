# Source releases and recovery

trego. is a travel navigator. The third source checkpoint is **v0.3.0**: the merged
saved-route editor (#80/#87), current travel positioning and consolidated documentation.
The release page and tag pin the exact reviewed commit. This document deliberately
does not embed its own future merge SHA. Publish the tag only after this update has
passed applicable checks and merged through the independent-review process.

## Checkpoints

| Version | Source | Release |
|---|---|---|
| v0.3.0 | Reviewed main after #80/#87 and the version-3 positioning/documentation update | [Third source checkpoint](https://github.com/uksus148/trego./releases/tag/v0.3.0) |
| v0.2.0-mvp-baseline | 9f65a86c16d36d51184182a8cf5ff90d7ab360c9 | [Second recovery checkpoint](https://github.com/uksus148/trego./releases/tag/v0.2.0-mvp-baseline) |
| v0.1.0-mvp-baseline | cfc4c648495511e6b8d21464f835028965cda388 | [First recovery checkpoint](https://github.com/uksus148/trego./releases/tag/v0.1.0-mvp-baseline) |

Each tag identifies the entire remote monorepo, including frontend, API, agent,
infrastructure and Flyway migrations. Service package versions need not equal the
checkpoint version. Published tags are fixed; do not move, replace or delete them.

## Version 3 scope and evidence

- #80 adds original endpoint snapshots, explicit nullable Place bindings, editing
  context and V4. #87 supplies the matching frontend draft/rebuild/session behavior.
- #87 head fbdc527 passed 125 frontend tests, lint/build and six actual-service
  Chromium scenarios in [CI](https://github.com/uksus148/trego./actions/runs/43687062740).
  After #80 merged, the retargeted merge tree was verified identical before #87 merged.
- Travel positioning updates visible descriptions and response wording; it does not
  introduce driving, cycling, transit, date-aware routing or personalization.
- The [documentation index](README.md) records retained contracts, deferred designs
  and the three redundant handoffs removed after checking their replacements.
- The version-3 PR and release notes record checks on that final update. Historical
  test counts are attributed to their original revisions, not treated as a new run.

Publish this checkpoint as a pre-release while final same-revision live acceptance
is outstanding. It is a recoverable source version, not proof of public deployment,
all-region routing/photo coverage or a new real-provider/model test. The [integration
runbook](INTEGRATION_RUNBOOK.md) retains the live gates and original evidence.

## Recover without rewriting main

Preserve any uncommitted work. In a separate clean checkout:

```sh
git fetch origin --tags
git rev-parse 'v0.3.0^{commit}'
git switch -c recovery/v0.3.0 v0.3.0
```

Compare the resolved SHA with the release page before running anything. For an
older checkpoint, substitute its exact tag and use a different recovery branch.
Read the environment template and service guides from the recovered revision.

Restoring shared main requires a separate reviewed revert PR and applicable checks.
Do not force-push, hard-reset or bypass branch protection to restore an older tag.

## Recovery boundaries

Git preserves source, not PostgreSQL data, Valkey contents, private .env files,
certificates, deployed configuration or external provider behavior. Keep database
backups and credentials outside this public repository.

V4 adds nullable route endpoint references. Source rollback does not reverse Flyway
migrations. Check schema compatibility before connecting older code to a newer
schema; never delete migration history to simulate rollback. Restoring data/schema
requires a separate backup and recovery plan.

## Publishing the next checkpoint

1. Merge reviewed changes with at least one independent approval and successful
   applicable checks. Confirm the final diff and exact remote-main commit.
2. Record verification and remaining live gates, with revision, environment and model
   for any real-provider evidence. Keep synthetic fixture evidence distinct.
3. Create a new tag at that exact commit and publish its release. Keep pre-release
   status until final live acceptance is recorded; never retarget an existing tag.
4. Verify the remote tag resolves to the intended commit and the published release
   references it. The release must not include local files or unmerged PR code.
