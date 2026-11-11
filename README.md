# memsift

**Find the problems in your coding agent’s memory. Review every change.**

[![CI](https://github.com/Arerii7/memsift/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/Arerii7/memsift/actions/workflows/ci.yml)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
![Status: preview](https://img.shields.io/badge/status-preview-orange)

memsift scans Markdown and explicit OpenCode memories for duplicates,
conflicting instructions, stale references, and possible secrets. Review the
findings in a local web interface, choose what to keep, and inspect the diff
before writing changes.

No account, external assets, telemetry, or cloud calls. Your index stays local.

[Quick start](#try-it) · [Checks](#what-it-checks) · [Safe writes](#review-and-write-changes) · [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

![Local review dashboard with synthetic sample findings](docs/review-dashboard.png)

## Try it

Requires Python 3.12 or newer and SQLite with FTS5. Tested on Linux and macOS;
Windows is not supported yet.

```bash
git clone https://github.com/Arerii7/memsift.git
cd memsift
python3 -m venv .venv
.venv/bin/pip install -e .
export MEMSIFT_HOME="$PWD/.memsift/demo"
.venv/bin/memsift init --path tests/fixtures/dirty
.venv/bin/memsift scan
.venv/bin/memsift doctor
.venv/bin/memsift review
```

The demo keeps its index and backups in the ignored `.memsift/demo/` directory.
It uses a **synthetic** key to demonstrate secret redaction. `review` starts
the interface at `http://127.0.0.1:8787`; open that address in your browser and
stop the server with `Ctrl+C`.

> **Preview:** Try memsift on a copy of your files first and review every diff.

> **Security:** memsift is a local, single-user tool. The review UI binds to
> loopback and has no authentication; never expose it to a network. The local
> index and backups can contain sensitive source content. See
> [SECURITY.md](SECURITY.md) for the threat model and reporting process.

To start your own index in the default storage directory:

```bash
unset MEMSIFT_HOME
.venv/bin/memsift init --path /path/to/notes
.venv/bin/memsift scan
.venv/bin/memsift review
```

Add a source with `.venv/bin/memsift scan --path /another/directory`; use
`--no-save` to scan it once. Run `.venv/bin/memsift --help` for all commands.

## What it checks

- Duplicate and similar records, and possible conflicts about the same topic.
- References to missing files, missing sources, and optionally expired records.
- Common patterns that look like credentials or private keys.
- `npm run` scripts in `AGENTS.md` and `CLAUDE.md` that are missing from the
  nearest `package.json`. Commands are inspected, never run.

Findings are suggestions, not facts: a detected conflict may be harmless, and
secret detection cannot guarantee that every credential will be found. Review
results before taking action.

## Explore your sources

```bash
.venv/bin/memsift sources --path /path/to/notes  # files, sizes and skipped folders
.venv/bin/memsift search 'database'             # search the local index
.venv/bin/memsift list                          # list indexed records
.venv/bin/memsift show RECORD_ID                # inspect a record and its history
```

Markdown discovery includes `MEMORY.md`, `AGENTS.md`, `CLAUDE.md`,
`.opencode/memory/**/*.md` and other Markdown files in the chosen directory.
Most hidden directories are skipped; `sources` shows what was found and which
hidden directories were skipped. It does not determine which files an agent
actually loads.

OpenCode import is read-only and looks for explicit `remember:`, `decision:`,
`preference:` and fenced `memory` entries:

```bash
.venv/bin/memsift import opencode --project /path/to/project
```

Use `--db /path/to/opencode.db` to choose a different OpenCode database.

## Review and write changes

Archiving, merging or editing a record in memsift does not immediately change
the source file. `sync` first shows a preview; source writes require `--apply`.
The web interface refuses an apply if its preview has changed. Resolving a
finding only closes that review item; use edit, merge, archive, or forget to
prepare a source change. Secret records cannot be edited or merged.

Only Markdown blocks with matching memsift anchors can be changed:

```md
<!-- memsift:id=ms_example -->
- We use SQLite.
<!-- /memsift:id=ms_example -->
```

To preview anchors for a file or directory, then add them explicitly:

```bash
.venv/bin/memsift anchor --path /path/to/notes
.venv/bin/memsift anchor --path /path/to/notes --apply
```

Malformed or duplicate anchors are rejected. Editing a claim or merging keeps
the canonical record’s remaining body text.

Adding anchors changes source files and creates backups. Review the preview
before applying. After reviewing records and approving changes:

```bash
.venv/bin/memsift sync          # preview
.venv/bin/memsift sync --apply  # confirm and write
.venv/bin/memsift history       # find the sync event ID
.venv/bin/memsift rollback EVENT_ID
```

memsift creates backups under `~/.local/share/memsift/backups/` by default;
`MEMSIFT_HOME` changes the storage location. Rollback refuses to overwrite a
file changed after sync or discard newer pending edits. Older sync events that
lack a post-sync hash cannot be rolled back automatically; their backups are
still available in the recorded backup directory.

Only anchored Markdown is writable. OpenCode's database is opened read-only and
is never modified. The local index and backups can contain sensitive source
content; redaction applies to displayed output and exports, not to the stored
source data. Keep the storage directory private.

If identical unanchored records are removed, their identities can be ambiguous.
memsift keeps previous decisions separate and asks you to add unique anchors and
review them manually.

## Development

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check .
.venv/bin/pytest --cov=src/memsift --cov-report=term-missing
```

Tests use local fixtures and should not make network requests. CI runs the suite
on Python 3.12–3.14 for Linux and on Python 3.12 for macOS. See
[CONTRIBUTING.md](CONTRIBUTING.md) for a short guide.

## Project documentation

- [Changelog](CHANGELOG.md) — fixes and release history.
- [Security](SECURITY.md) — storage, threat model, and vulnerability reports.
- [Specification](docs/SPEC.md) — records, detectors, and sync rules.
- [Design](docs/DESIGN.md) — interface layout and visual rules.
- [Implementation plan](docs/PLAN.md) — completed work and follow-ups.

## License

[MIT](LICENSE)
