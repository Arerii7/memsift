from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

from .models import now_ms

_LEADING_MARKERS = re.compile(
    r"""^\s*(?:
        [-*+]\s+(?:\[[ xX]\]\s+)? |
        \d+[.)]\s+ |
        (?:\*\*|__)?(?:remember|decision|preference|fact|note|memory|context|learned|todo)
            (?:\*\*|__)?\s*[:=]\s* |
        \[(?:remember|decision|preference|fact|note|memory)\]\s* |
        \[[a-zA-Z0-9_.\-]+/[a-zA-Z0-9_.\-]+\]\s* |
        [a-zA-Z][a-zA-Z0-9_.\-]+/[a-zA-Z0-9_.\-]+\s*[:=]\s*
    )""",
    re.IGNORECASE | re.VERBOSE,
)

_EXPLICIT_TOPIC = re.compile(
    r"""^\s*(?:
        (?:topic|key)\s*[:=]\s*(?P<key1>[a-zA-Z0-9_.\-]+/[a-zA-Z0-9_.\-]+) |
        \[(?P<key2>[a-zA-Z0-9_.\-]+/[a-zA-Z0-9_.\-]+)\] |
        (?P<key3>[a-zA-Z][a-zA-Z0-9_.\-]+/[a-zA-Z0-9_.\-]+)\s*[:=]
    )""",
    re.VERBOSE,
)

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "but",
    "by",
    "for",
    "from",
    "has",
    "have",
    "he",
    "her",
    "his",
    "i",
    "in",
    "is",
    "it",
    "its",
    "me",
    "my",
    "of",
    "on",
    "or",
    "our",
    "ours",
    "she",
    "so",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "to",
    "was",
    "we",
    "were",
    "will",
    "with",
    "you",
    "your",
    "use",
    "used",
    "uses",
    "using",
    "now",
    "still",
    "also",
    "just",
    "can",
    "should",
    "would",
    "could",
    "database",
    "db",
    "primary",
    "provider",
    "target",
    "stack",
    "project",
    "setup",
    "configuration",
    "config",
    "app",
    "application",
    "и",
    "в",
    "во",
    "не",
    "на",
    "с",
    "со",
    "как",
    "это",
    "для",
    "по",
    "из",
    "к",
    "у",
    "мы",
    "вы",
    "они",
    "он",
    "она",
    "оно",
    "наш",
    "наша",
    "наше",
    "их",
    "был",
    "была",
    "было",
    "быть",
    "есть",
    "или",
    "но",
    "что",
    "чтобы",
    "при",
    "от",
    "до",
    "же",
    "уже",
    "теперь",
    "сейчас",
    "используем",
    "используется",
    "использовать",
    "база",
    "бд",
    "основная",
}


def clean_claim(text: str) -> str:
    """Turn a memory block's first line into a readable one-line claim."""
    value = text.strip()
    for _ in range(3):
        cleaned = _LEADING_MARKERS.sub("", value, count=1)
        cleaned = cleaned.strip().strip("*_` ")
        if cleaned == value:
            break
        value = cleaned
    value = re.sub(r"\s+", " ", value)
    return value.strip().strip("\"'")


def tokens(text: str) -> list[str]:
    cleaned = clean_claim(text).lower()
    cleaned = re.sub(r"[^\w./+-]+", " ", cleaned, flags=re.UNICODE)
    result = []
    for token in cleaned.split():
        token = token.strip("._-")
        if not token or token in _STOPWORDS:
            continue
        result.append(token)
    return result


def normalize_claim(text: str) -> str:
    """Stable token signature used for duplicate and conflict detection."""
    unique = sorted(set(tokens(text)))
    return " ".join(unique) if unique else clean_claim(text).lower()


def token_set(text: str) -> set[str]:
    return set(tokens(text))


def jaccard(left: str, right: str) -> float:
    a = token_set(left)
    b = token_set(right)
    if not a or not b:
        return 1.0 if a == b else 0.0
    return len(a & b) / len(a | b)


def _explicit_topic(text: str) -> str | None:
    text = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", text)
    match = _EXPLICIT_TOPIC.match(text)
    if not match:
        return None
    key = match.group("key1") or match.group("key2") or match.group("key3")
    return key.lower().strip("./-") if key else None


# Value -> topic. Values are matched as whole words/phrases.
_TOPIC_VALUES: list[tuple[str, tuple[str, ...]]] = [
    (
        "auth/provider",
        (
            "clerk",
            "nextauth",
            "auth0",
            "lucia",
            "better auth",
            "firebase auth",
            "supabase auth",
            "keycloak",
            "oauth",
            "jwt",
            "session auth",
        ),
    ),
    (
        "stack/database",
        (
            "postgres",
            "postgresql",
            "sqlite",
            "mysql",
            "mariadb",
            "mongodb",
            "redis",
            "supabase",
            "neon",
            "prisma",
            "drizzle",
            "duckdb",
            "clickhouse",
        ),
    ),
    (
        "deploy/target",
        (
            "vercel",
            "netlify",
            "railway",
            "render",
            "fly.io",
            "heroku",
            "aws",
            "gcp",
            "azure",
            "cloudflare",
            "docker",
            "kubernetes",
        ),
    ),
    (
        "tool/package-manager",
        ("npm", "pnpm", "yarn", "bun", "pip", "poetry", "uv", "cargo", "go mod"),
    ),
    (
        "tool/test-runner",
        ("pytest", "jest", "vitest", "playwright", "cypress", "unittest", "mocha"),
    ),
    (
        "ui/framework",
        ("react", "vue", "svelte", "solid", "next.js", "nextjs", "nuxt", "astro", "htmx"),
    ),
    (
        "ui/styling",
        ("tailwind", "css modules", "styled-components", "sass", "bootstrap", "vanilla css"),
    ),
    (
        "stack/language",
        ("python", "typescript", "javascript", "rust", "golang", "java", "ruby", "php", "elixir"),
    ),
    (
        "tool/linter",
        ("ruff", "eslint", "biome", "prettier", "flake8", "black"),
    ),
]

_AUTH_WORDS = ("auth", "authentication", "authorization", "login", "sign-in", "signin")
_DB_WORDS = ("database", " db", "база данных", "бд", "storage layer")


def infer_topic(text: str) -> str | None:
    explicit = _explicit_topic(text)
    if explicit:
        return explicit
    lowered = " " + clean_claim(text).lower() + " "
    best: tuple[int, str] | None = None
    for topic, values in _TOPIC_VALUES:
        for value in values:
            idx = lowered.find(value)
            if idx < 0:
                continue
            # Avoid matching "go" inside ordinary words or "aws" inside "laws".
            before = lowered[idx - 1] if idx else " "
            after = lowered[idx + len(value)] if idx + len(value) < len(lowered) else " "
            if value.isalnum() and (before.isalnum() or after.isalnum()):
                continue
            if best is None or idx < best[0]:
                best = (idx, topic)
    if best:
        return best[1]
    if any(word in lowered for word in _DB_WORDS):
        return "stack/database"
    if any(word in lowered for word in _AUTH_WORDS):
        return "auth/provider"
    return None


_FILE_REF = re.compile(
    r"""(?<![\w/.-])
        ((?:~?[\w.@+-]+/)*[\w.@+-]+\.(?:py|pyi|js|jsx|ts|tsx|mjs|cjs|go|rs|java|rb|php|
        css|scss|html|md|json|jsonl|toml|yaml|yml|sql|sh|bash|zsh|env|ini|cfg|lock))
        (?::\d+(?::\d+)?)?""",
    re.VERBOSE | re.IGNORECASE,
)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)


def extract_file_refs(text: str) -> list[str]:
    without_urls = _URL.sub(" ", text)
    found: list[str] = []
    for match in _FILE_REF.finditer(without_urls):
        raw = match.group(1).strip()
        if raw.startswith(("~", "/")) or "/" in raw:
            found.append(raw)
            continue
        # Bare filenames are useful only for common project files.
        if raw.lower() in {
            "memory.md",
            "agents.md",
            "claude.md",
            "readme.md",
            "pyproject.toml",
            "package.json",
            "docker-compose.yml",
            "docker-compose.yaml",
            "requirements.txt",
            "cargo.toml",
            "go.mod",
        }:
            found.append(raw)
    return list(dict.fromkeys(found))


_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("github", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("aws", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    (
        "private-key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
            r"[\s\S]*?(?:-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|$)",
            re.IGNORECASE,
        ),
    ),
    ("bearer", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE)),
    (
        "assignment",
        re.compile(
            r"""(?ix)
            \b(?:api[_-]?key|secret|client[_-]?secret|access[_-]?token|auth[_-]?token|
                refresh[_-]?token|password|passwd|pwd)\b
            \s*[:=]\s*["']?(?P<value>[A-Za-z0-9_./+=:@-]{8,})
            """
        ),
    ),
    (
        "env-secret",
        re.compile(
            r"""(?ix)
            ^\s*(?:export\s+)?(?:[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|PWD)[A-Z0-9_]*)
            \s*=\s*["']?(?P<value>[^"'\s#]{8,})
            """
        ),
    ),
    ("private-tag", re.compile(r"<private>.*?</private>", re.IGNORECASE | re.DOTALL)),
)

_PLACEHOLDERS = (
    "<",
    ">",
    "${",
    "{{",
    "your_",
    "your-",
    "example",
    "placeholder",
    "changeme",
    "change_me",
    "redacted",
    "****",
    "xxxx",
    "...",
)


def secret_matches(text: str) -> list[re.Match[str]]:
    matches: list[re.Match[str]] = []
    for _name, pattern in _SECRET_PATTERNS:
        for match in pattern.finditer(text):
            value = match.groupdict().get("value") or match.group(0)
            if any(marker in value.lower() for marker in _PLACEHOLDERS):
                continue
            if value.lower() in {"password", "secret", "token", "apikey", "api_key"}:
                continue
            matches.append(match)
    return matches


def sensitivity_for(text: str) -> str:
    return "secret" if secret_matches(text) else "normal"


def redact_text(text: str) -> str:
    result = text
    for _name, pattern in _SECRET_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


def redact_diff(text: str) -> str:
    masked = redact_text(text)
    return "".join(
        line[0] + redact_text(line[1:]) if line and line[0] in " +-" else redact_text(line)
        for line in masked.splitlines(keepends=True)
    )


def redact_record_body(record: object) -> str:
    body = getattr(record, "body", "")
    return redact_text(str(body))


def stable_memory_id(
    source_kind: str,
    source_ref: str,
    claim: str,
    occurrence: int = 0,
    explicit: str | None = None,
) -> str:
    if explicit:
        return explicit
    digest = hashlib.sha256(
        f"{source_kind}\x1f{source_ref}\x1f{normalize_claim(claim)}\x1f{occurrence}".encode()
    ).hexdigest()
    return f"ms_{digest[:16]}"


def score_confidence(
    *,
    source_kind: str,
    claim: str,
    explicit: bool = False,
    pinned: bool = False,
    topic_key: str | None = None,
    files: list[str] | None = None,
    created_at: int | None = None,
) -> float:
    if source_kind == "opencode":
        score = 0.9 if explicit else 0.75
    elif source_kind == "markdown":
        score = 0.85 if explicit else 0.75
    else:
        score = 0.7
    if pinned:
        score += 0.12
    if topic_key:
        score += 0.03
    if files:
        score += 0.02
    if created_at:
        age_days = max(0.0, (now_ms() - created_at) / 86_400_000)
        score -= min(0.2, age_days / 3650)
    if claim.lower().startswith(("maybe", "perhaps", "not sure", "возможно")):
        score -= 0.1
    return round(max(0.05, min(1.0, score)), 3)


def human_age(timestamp_ms: int) -> str:
    delta = max(0, now_ms() - timestamp_ms)
    minutes = delta // 60_000
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def date_only(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).strftime("%Y-%m-%d")


def is_relative_path(value: str) -> bool:
    path = Path(value)
    return not path.is_absolute() and not value.startswith("~")
