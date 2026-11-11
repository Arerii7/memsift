# memsift implementation plan

Status: v0.1.0 vertical slice complete and verified on 2026-11-10.

## Stage 0 — Bootstrap

- [x] pyproject, editable install, CLI entry point
- [x] config paths + `init`
- [x] SQLite schema + FTS5
- [x] SPEC/PLAN/AGENTS, README
- [x] smoke tests, ruff, first commit

## Stage 1 — Data + Markdown

- [x] normalization and stable IDs
- [x] Markdown parser with provenance
- [x] `scan`, `list`, `show`
- [x] dirty/clean fixtures
- [x] idempotent re-scan test
- [x] FTS5 search

## Stage 2 — Detectors + doctor

- [x] duplicates (exact + Jaccard)
- [x] conflicts (topic-key based)
- [x] stale file references
- [x] orphans
- [x] secrets (keys, tokens, private keys, bearer)
- [x] confidence scoring
- [x] `doctor` table/json
- [x] exact findings on dirty fixture; zero on clean
- [x] dismiss/resolve decisions survive re-scan

## Stage 3 — Review UI

- [x] dashboard
- [x] queue + filters
- [x] detail with provenance/history
- [x] merge side-by-side
- [x] action endpoints + audit
- [x] sync preview page
- [x] settings
- [x] alpha secret editing disabled

## Stage 4 — Sync

- [x] anchored block parser
- [x] update/delete plan
- [x] unified diff
- [x] backup + atomic write
- [x] rollback exact bytes
- [x] `anchor` command
- [x] end-to-end archive → sync → rollback demo

## Stage 5 — OpenCode adapter

- [x] read-only session reader
- [x] explicit markers only
- [x] provenance (session/message)
- [x] synthetic-schema tests
- [x] source DB unchanged test

## Stage 6 — Polish

- [x] README quickstart + safety
- [x] `--json` on machine-readable commands
- [x] secret redaction
- [x] packaging (editable install)
- [ ] publish to PyPI (not requested yet)
- [x] final verification: ruff + 31 tests

## Known boundaries

- Only anchored Markdown blocks are writable. Run `memsift anchor` first.
- Review UI uses plain HTML forms (no external HTMX download, fully offline).
- Terminal statuses and finding decisions survive rescans; a changed source hash
  may produce a new finding id, which is treated as a new review item.
- LLM judge is intentionally not implemented in v1.

## Follow-up — Safe sync

- [x] Skip files changed since scanning and refuse stale sync plans.

## Follow-up — Practical discovery and review

- [x] Detect missing `npm run` scripts in instruction files without executing commands.
- [x] Show discovered memory files and skipped hidden directories.
- [x] Add CLI search over indexed memories with redacted output.
- [x] Show instruction file sizes and line counts in source inventory.

## Follow-up — Audit fixes

- [x] Protect local web actions and redact sync previews.
- [x] Restrict access to the local index and backups.
- [x] Preserve files and index during sync failures and rollback.
- [x] Reconcile changed Markdown records and distinguish projects.
- [x] Correct anchored fenced memory and npm command punctuation.
- [x] Avoid reassigning decisions when identical unanchored records are removed.

## Follow-up — Repository presentation

- [x] Document the preview release, safe first run, and contribution workflow.
- [x] Ignore local credentials and development artifacts.
- [x] Put the product summary and first run at the top of the README.
- [x] Add clone instructions and a dashboard screenshot using sample data.

## Follow-up — Release readiness

- [x] CI for Python 3.12–3.14 on Linux and Python 3.12 on macOS.
- [x] `--version` flag and a single source for the package version.
- [x] Release metadata, README badges, and complete sdist contents.
- [x] Security policy, changelog, and platform support note.
- [ ] Publish to PyPI (not requested yet).

## Follow-up — Review UI redesign

- [x] Dark terminal/editorial theme with a warm clay accent.
- [x] Numbered left rail and segmented health meter.
- [x] Responsive 360px layout, visible focus states, reduced motion.
- [x] Dashboard, queue, detail, merge, sync, and settings screens.

## Follow-up — Review safety and repository cleanup

- [x] Reject malformed anchors before sync can modify unrelated content.
- [x] Bind web apply to the reviewed diff and reject stale previews.
- [x] Protect secret records during merge and preserve multiline record bodies.
- [x] Keep source hashes consistent across successive sync and rollback operations.
- [x] Check review UI actions and copy; make merge selection explicit.
- [x] Simplify repository presentation, ignore local artifacts, and organize internal docs.
- [x] Verify lint, 110 tests (89.66% coverage), sdist/wheel, and installed web assets.
- [x] Independent review: reject nested anchors inside memory fences; regression test added.
- [x] Publish the reviewed commit to GitHub (3917a5d, master).

## Follow-up — Current dashboard screenshot

- [x] Refresh the README screenshot from the current UI in Firefox at 1440 × 1400 using synthetic demo data.
