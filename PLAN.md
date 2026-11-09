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
