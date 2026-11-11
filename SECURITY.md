# Security policy

memsift reads potentially sensitive memory files, stores a local index, and can
write approved changes back to Markdown sources. Security reports are welcome.

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.x | Yes |

## Reporting a vulnerability

Use GitHub's private vulnerability reporting:
<https://github.com/Arerii7/memsift/security/advisories/new>

Please do not open a public issue for a suspected vulnerability. Include:

- the affected version and operating system;
- a minimal reproduction using synthetic data;
- the impact you believe is possible;
- any suggested fix.

Do not attach real memories, tokens, session databases or other private data.

## Threat model

memsift is a local, single-user command-line tool and review UI. It is not a
multi-user service.

- The review UI binds to loopback only and has no authentication. CSRF tokens
  and host checking protect against cross-site requests, but anyone who can
  reach `127.0.0.1:8787` on the machine can use the UI.
- Do not expose the review UI through a reverse proxy, port forwarding, tunnel
  or container port mapping.
- The SQLite index and backups can contain sensitive source content. Redaction
  applies to displayed output and exports, not to stored source data. The data
  directory is created with private permissions; keep it private.
- OpenCode's database is opened read-only and is never modified.
- Source writes require an approved plan, matching anchors, a content hash
  check, a backup and an atomic replace. Rollback refuses to overwrite files
  that changed after sync.

## In scope

- bypassing preview-first writes or anchor restrictions;
- path traversal or symlink attacks against the index, backups or sync;
- cross-site scripting, CSRF or host-header bypass in the review UI;
- secret disclosure in the UI, CLI output, JSON output, diffs or exports;
- permission mistakes that expose the index or backups to other users;
- denial of service that corrupts data rather than merely being slow.

## Out of scope

- running with a non-loopback `--host` (the CLI refuses this);
- heuristics that miss a real secret or flag a harmless sentence, unless the
  result leaks data or writes to the wrong file;
- vulnerabilities in dependencies that are already fixed upstream;
- social engineering or access to an already-compromised user account.

## User responsibilities

- Review every sync preview before applying it.
- Keep Python, dependencies and the operating system up to date.
- Do not use memsift on a machine you do not trust.
- Remove the index and backups with ordinary file tools when no longer needed.
