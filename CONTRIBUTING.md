# Contributing

Bug reports and small, focused pull requests are welcome. The project is an
early preview; clear reproduction steps are especially useful.

## Set up

Use Python 3.12 or newer:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check .
.venv/bin/pytest
```

Tests must run without network access. Use temporary files and synthetic data;
do not include real memories, API keys or session databases in fixtures, issues
or pull requests.

## Before opening a pull request

- Describe the problem and how to reproduce it.
- Keep changes focused and add tests for changed behavior.
- Run Ruff and pytest using the commands above.
- Update the README when user-facing behavior changes.
- Preserve the read-only OpenCode adapter and preview-first source writes.

For bugs involving sync or rollback, please include the expected and actual
behavior using a small synthetic Markdown example. Review issue text and logs
for private information before posting.
