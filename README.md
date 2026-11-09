# memsift

**Sift your agent's memory.** A local CLI + review UI that finds duplicates,
contradictions, stale facts, orphans, and secrets in AI-agent memory, then writes
the cleaned result back safely.

```bash
memsift init
memsift scan --path ~/notes
memsift doctor
memsift review
```

No cloud. No accounts. No vector database. No LLM required. Markdown stays
Markdown, and `opencode.db` is only ever read.

## What it does

- reads Markdown memory (`MEMORY.md`, `AGENTS.md`, `CLAUDE.md`, `.opencode/memory/*.md`)
  and OpenCode session messages (read-only);
- indexes records in local SQLite with FTS5;
- finds exact/near duplicates, topic conflicts, stale file references, orphans,
  and secrets;
- gives you a local review queue at `127.0.0.1:8787`;
- writes approved changes back with backups, atomic writes, and rollback.

## Install from this repository

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/memsift --help
```

## A safe first run

```bash
# create ~/.local/share/memsift and register the current directory
memsift init

# read configured sources and run detectors
memsift scan

# inspect what was found
memsift doctor
memsift list --status conflict

# review in the browser
memsift review

# always preview writes first
memsift sync --dry-run
```

Only anchored Markdown blocks are writable:

```md
<!-- memsift:id=ms_abc123 -->
- We use SQLite.
<!-- /memsift:id=ms_abc123 -->
```

Run `memsift anchor --path ~/notes --apply` to add anchors around existing
memory blocks. The command is non-destructive and makes a backup first.

## Commands

| Command | Purpose |
|---|---|
| `memsift init` | create local database and config |
| `memsift scan` | ingest sources + run detectors |
| `memsift doctor` | print memory health report |
| `memsift sources [--path DIR]` | list Markdown files, size and skipped hidden folders |
| `memsift search QUERY` | search indexed memory and show its source |
| `memsift list` | list memories by status/scope |
| `memsift show ID` | show provenance, findings, history |
| `memsift review` | open the local review UI |
| `memsift merge A B --claim ...` | merge two records |
| `memsift supersede OLD NEW` | mark one record as replaced |
| `memsift archive/forget/pin/restore ID` | curate a record |
| `memsift sync [--apply]` | preview or write approved changes |
| `memsift history [ID]` | audit trail |
| `memsift rollback EVENT` | restore files from a sync backup |
| `memsift export` | export clean Markdown or JSON |
| `memsift anchor` | add writable block anchors |
| `memsift import opencode` | import explicit memory markers from sessions |

## Safety model

- Source stores are read-only; only anchored Markdown blocks can be written.
- `sync` defaults to `--dry-run`.
- Every write is backed up under `.memsift/backups/<timestamp>/`.
- Writes are atomic (temp file + rename).
- `memsift rollback <event>` restores exact bytes.
- Secrets are redacted in the UI/JSON and excluded from export.
- No network calls are made by the core pipeline.

`doctor` also reports `npm run` scripts referenced in `AGENTS.md` or `CLAUDE.md`
that are absent from the nearest `package.json`. It reads manifests but never
executes commands; a missing or invalid manifest is not treated as a finding.
Examples that change directories are skipped because their working directory
cannot be inferred reliably.
The `sources` command follows the same discovery rules as `scan`, and its
counts describe files found on disk rather than the agent's effective context.

## Status

`0.1.0` is a functional local-first v1. The review UI covers dashboard, queue,
detail, merge, and sync preview. OpenCode import is read-only and only picks up
explicit `remember:`, `decision:`, `preference:` markers or fenced `memory`
blocks.

## Development

```bash
.venv/bin/ruff check .
.venv/bin/pytest
```
