# MVP recovery baseline

This source checkpoint preserves the merged implementation before the local
landmark-media feature. It is published as a pre-release, not final MVP acceptance.

| Item | Pinned value |
|---|---|
| Tag | `v0.1.0-mvp-baseline` |
| Commit | `cfc4c648495511e6b8d21464f835028965cda388` |
| Source | `main` after merged PR #68 |
| Release | [MVP recovery checkpoint](https://github.com/uksus148/trego./releases/tag/v0.1.0-mvp-baseline) |

This document is a follow-up to the published checkpoint. Its own commit is not
part of that tag. The tag identifies the whole monorepo; it does not change the
individual Maven, Python, or npm package versions.

## What is preserved

The tagged tree contains the frontend, Java API, agent, infrastructure files and
Flyway migrations at the pinned revision. It includes the agent stabilization
changes merged through #68. Local uncommitted landmark-media changes are excluded.

PR #68 passed [Agent checks](https://github.com/uksus148/trego./actions/runs/43664608997)
on PR head `7ec728bad4ac909de81cd50b1ca1db55b325e8df`. Publishing the checkpoint did
not run a new live E2E test. Earlier evidence, including issue #63, must retain its
original revision and model; it is not acceptance of this exact commit.

## Recover without rewriting main

Preserve any uncommitted work before switching branches. From a clean worktree:

```sh
git fetch origin --tags
git rev-parse 'v0.1.0-mvp-baseline^{commit}'
git switch -c recovery/mvp-baseline v0.1.0-mvp-baseline
```

The resolved commit must equal the pinned commit in the table above. Choose a new
recovery branch name if that branch already exists. Start services using the
instructions and environment template from the recovered revision.

Use this branch to diagnose a regression or run the baseline. Restoring shared
`main` requires a separate reviewed PR that reverts the relevant changes, followed
by applicable checks and live acceptance. Do not force-push or hard-reset shared
`main` to the tag.

## Recovery boundaries

Git preserves source, not PostgreSQL data, Valkey contents, private `.env` files,
certificates, service configuration, or external provider behavior. A source
checkpoint does not guarantee a byte-for-byte reproducible runtime environment.

Before running old code against a database changed by later migrations, check
schema compatibility. Do not delete migration history or assume that switching
Git revisions reverses Flyway migrations. A data/schema rollback needs its own
backup and recovery plan. Keep credentials and backups outside this public repo.

## Subsequent versions

1. Merge changes through the normal PR process with at least one independent
   approval and successful applicable checks.
2. Record the exact merged commit, check results, and live E2E evidence, including
   the model and environment used. Final MVP acceptance requires live evidence on
   the selected revision and the primary 20b model.
3. Publish a new version tag and release at that exact commit. Keep pre-release
   status while acceptance gates remain open.
4. Treat published tags as fixed: never move, reuse, or delete this baseline tag
   to include later fixes. Publish a new version instead.

These are team conventions. This PR does not add tag-protection rules, CI workflows,
or automated releases; the existing main-branch review rules continue to apply.
