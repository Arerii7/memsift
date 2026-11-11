# AGENTS.md — working agreement for memsift

## Mission

Keep the project deterministic, safe, and easy for an AI agent to continue.
The repository is the memory: update `docs/PLAN.md` and tests with every slice.

## Rules

1. Read `docs/SPEC.md` and the current unchecked item in `docs/PLAN.md` before coding.
2. Vertical slices only: database -> CLI/UI -> test -> demo -> commit.
3. Never write to `~/.local/share/opencode/opencode.db` or any third-party store.
4. `memsift sync` defaults to dry-run. No source file changes without approval.
5. Every write path needs: backup, temp file, fsync, rename, audit event.
6. Secrets must not appear in UI/JSON/export; use redaction helpers.
7. Network is forbidden in tests. Mock optional LLM work.
8. Run `.venv/bin/ruff check .` and `.venv/bin/pytest` after changes.
9. If a fix fails three times, change the approach instead of piling on patches.
10. Keep tests small, named for behavior, and backed by fixtures.

## Commands

```bash
.venv/bin/ruff check .
.venv/bin/pytest
.venv/bin/memsift --help
```

## Layout

- `src/memsift/` — package
- `src/memsift/ingest/` — read-only source adapters
- `src/memsift/detect/` — pure detector functions
- `src/memsift/web/` — local FastAPI review UI
- `tests/fixtures/` — dirty, clean, and synthetic OpenCode data

## Definition of done

- tests pass; ruff passes;
- behavior is demonstrated with a command;
- `docs/PLAN.md` checkbox updated;
- no unrelated refactors.
