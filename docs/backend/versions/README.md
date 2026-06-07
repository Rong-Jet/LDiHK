# Backend Version Story Structure

This directory stores backend version history as one Markdown file per version.
Each version file should read like a user story ticket: it captures the product
intent, the feature set, and the acceptance criteria that define when that
backend version is complete.

## Naming

Use this filename pattern:

```text
v{major}-{short-kebab-name}.md
```

Examples:

```text
v1-youtube-usage-pipeline-api.md
v2-multi-user-ingestion.md
v3-duration-estimation.md
```

## Current Version Index

- `v1-youtube-usage-pipeline-api.md`
- `v2-youtube-temporal-api.md`
- `v3-sql-duration-query-api.md`
- `v4-youtube-takeout-s3-postgres-backend.md`
- `v5-hosted-backend-workers-and-deployment.md`

## Required Structure

Every version file must use these sections, in this order:

```md
# vN: Short Version Name

## Status

One of: Proposed, In Progress, Completed, Superseded.

## Summary

One short paragraph describing what this backend version adds and why it exists.

## User Story

As a [user or system actor], I want [capability], so that [outcome].

## Feature Set

- Concrete capability 1.
- Concrete capability 2.
- Concrete capability 3.

## Public Contract

Document any stable API routes, CLI commands, output files, schemas, status
codes, or compatibility guarantees introduced by this version.

## Acceptance Criteria

- [ ] Observable behavior that must work.
- [ ] Error or edge-case behavior that must work.
- [ ] Privacy, safety, or compatibility condition that must hold.

## Verification

List the tests, scripts, smoke checks, or manual checks used to verify the
version.

## Out Of Scope

List tempting work that is intentionally excluded from this version.

## Notes

Optional implementation notes, follow-ups, tradeoffs, or links.
```

## Rules

- Keep acceptance criteria observable from the public interface.
- Prefer behavior language over implementation details.
- Do not include raw personal data, titles, URLs, channel names, or other
  content-specific source data in version files.
- Mark completed criteria with `[x]` only after the behavior has been
  implemented and verified.
- If a later version replaces behavior, create a new version file and mark the
  older one `Superseded`; do not rewrite history except to fix factual errors.
