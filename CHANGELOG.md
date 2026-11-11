# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

### Known limitations

- Writing is supported only for Markdown blocks wrapped in memsift anchors.
- Detectors are heuristics, not guarantees.
- Linux and macOS are supported; Windows is not supported yet.
- The LLM judge and cloud sync are intentionally out of scope for v1.
