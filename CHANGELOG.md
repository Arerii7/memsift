# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Redesigned the local review UI with a dark terminal/editorial theme, a
  numbered rail, a segmented health meter, and responsive layouts down to
  360px.

### Fixed

- Reject unclosed, mismatched, nested, and duplicate Markdown anchors before
  they can modify unrelated source content.
- Bind web sync approval to the displayed plan and reject stale previews.
- Prevent editing or merging secret records, including direct form submissions.
- Preserve multiline canonical content when editing or merging a claim.
- Refresh source hashes for unchanged records after sync and rollback so
  successive writes do not require an unnecessary rescan.
- Compare merge selections before submission and show finding decisions.

### Documentation

- Isolate the quick-start demo index, simplify the README, and organize internal
  specification, design, and implementation notes under `docs/`.
- Ignore local agent settings, credentials, coverage artifacts, and temporary files.

## [0.1.0] — 2026-11-11

First public preview.

### Added

- Deterministic detectors for duplicates, conflicts, stale references,
  orphans, possible secrets and missing `npm run` scripts.
- Local SQLite/FTS5 index with `scan`, `doctor`, `search`, `list`, `show`,
  `sources` and `history` commands.
- Local FastAPI review UI with dashboard, queue, detail, merge and sync
  preview screens.
- Anchored Markdown sync with dry-run preview, timestamped backups, atomic
  writes, content hash checks and exact rollback.
- Read-only OpenCode memory import for explicit `remember:`, `decision:`,
  `preference:` and fenced `memory` entries.
- Secret redaction in the UI, CLI output, JSON output, diffs and exports.
- JSON output for machine-readable commands.
- CI for Python 3.12–3.14 on Linux and Python 3.12 on macOS.
- Security policy and threat model.

### Security

- Review UI is loopback-only with CSRF tokens and host-header checking.
- Index, backups and configuration live in a private data directory.
- Source files change only after an approved sync; OpenCode data stays
  read-only.

### Fixed

- Event and detector-run ids are random, so two appends in the same millisecond
  can no longer collide.

### Known limitations

- Writing is supported only for Markdown blocks wrapped in memsift anchors.
- Detectors are heuristics, not guarantees.
- Linux and macOS are supported; Windows is not supported yet.
- The LLM judge and cloud sync are intentionally out of scope for v1.
