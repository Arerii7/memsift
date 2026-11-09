# memsift specification

## Product

`memsift` is a memory-hygiene layer for AI agents. It reads existing memory
stores, builds a local index, finds deterministic problems, and lets a human
approve cleanup. It is not another memory store and does not decide facts with
an LLM.

## Users

1. Developers with several coding agents whose memory files disagree.
2. Maintainers of a Markdown "second brain" that has grown duplicates.
3. OpenCode users who want to review what their sessions saved.

## Core loop

```
sources -> normalize -> SQLite/FTS5 -> detectors -> review queue
        -> approved actions -> diff -> backup -> atomic write -> audit
```

## Sources

### Markdown (v1)

- `MEMORY.md`, `AGENTS.md`, `CLAUDE.md`
- `.opencode/memory/**/*.md`
- any user-provided directory of `.md` files

Markdown memory blocks are bullet items, paragraphs under memory-like headings,
and fenced ` ```memory ` blocks. Writable blocks must be wrapped in
`<!-- memsift:id=ID -->` / `<!-- /memsift:id=ID -->` anchors.

### OpenCode (v1, read-only)

Reads `session_message` and `session_v2` from the OpenCode SQLite database.
Only explicit lines are imported:

- `remember: ...`
- `decision: ...`
- `preference: ...`
- fenced ` ```memory ` blocks

The OpenCode database is opened read-only and never modified.

## Records

A memory record has a stable ID, claim, original body, optional topic key,
scope, provenance, timestamps, confidence, status, sensitivity, and a pending
sync action. `topic_key` makes conflicts structural: records that talk about
the same subject share a key.

## Detectors

| Kind | Rule |
|---|---|
| duplicate | identical normalized claim, or token Jaccard >= 0.8 |
| conflict | same scope + `topic_key`, different normalized claim |
| stale | referenced file is missing, or optional TTL expired |
| orphan | no provenance, or Markdown source file no longer exists |
| secret | API key / token / private key / password patterns |
| superseded | same topic with a newer record, surfaced as a conflict/merge candidate |

Each finding has a stable ID, severity, score, human-readable title, and related
record. Re-running detection is idempotent for the same inputs.

## Statuses

`active`, `duplicate`, `conflict`, `stale`, `orphan`, `archived`, `rejected`,
`forgotten`.

Terminal statuses (`archived`, `rejected`, `forgotten`) survive rescans.

## Actions

`approve`, `reject`, `merge`, `supersede`, `pin`, `archive`, `forget`, `restore`,
`edit`, `sync`, `rollback`.

Every action writes an event with before/after JSON. Deleting from a source is
possible only through `sync --apply` after an approved `archive`/`forget`.

## Sync rules

- Default is `--dry-run`.
- Only anchored Markdown blocks are changed.
- `update` replaces the block content, preserving anchors.
- `delete` removes the whole anchored block.
- Secret records are never exported.
- Apply creates a timestamped backup, writes a temp file, fsyncs, and renames.
- A sync event stores enough information for exact rollback.

## Review UI

Local FastAPI + Jinja2 app bound to `127.0.0.1`. Screens:

- dashboard: status/finding counts and health score;
- queue: findings filtered by kind;
- detail: body, provenance, related records, history;
- merge: side-by-side records with canonical selection;
- sync preview: unified diff and apply;
- settings: paths and configured sources.

No authentication, external assets, telemetry, or cloud calls.

## Non-goals

- vector database or RAG engine;
- autonomous fact extraction;
- cloud sync or multi-user SaaS;
- writing to third-party stores;
- LLM judgment by default.

## Success criteria

- re-scan of unchanged files is idempotent;
- dirty fixture yields exactly the expected finding kinds;
- clean fixture yields zero findings;
- no source byte changes without an approved sync;
- rollback restores exact bytes;
- full test suite passes offline.
