from memsift.normalize import (
    clean_claim,
    extract_file_refs,
    infer_topic,
    normalize_claim,
    redact_text,
    secret_matches,
    sensitivity_for,
    stable_memory_id,
)


def test_clean_claim_removes_markdown_and_markers() -> None:
    assert clean_claim("- [x] remember: We use SQLite.") == "We use SQLite."
    assert clean_claim("decision: Use NextAuth.") == "Use NextAuth."
    assert clean_claim("[db/primary] SQLite") == "SQLite"


def test_normalize_claim_is_token_order_independent() -> None:
    assert normalize_claim("We use SQLite") == normalize_claim("SQLite is used")
    assert normalize_claim("We use Postgres") != normalize_claim("SQLite is used")


def test_topic_inference() -> None:
    assert infer_topic("We use Postgres for the database") == "stack/database"
    assert infer_topic("Authentication uses NextAuth") == "auth/provider"
    assert infer_topic("Deploy target is Vercel") == "deploy/target"
    assert infer_topic("[billing/currency] EUR") == "billing/currency"
    assert infer_topic("- [billing/currency] EUR") == "billing/currency"
    assert infer_topic("The office is on the second floor") is None


def test_file_references() -> None:
    refs = extract_file_refs("See `src/app.py:12` and deploy/prod.yml. Also memory.md.")
    assert "src/app.py" in refs
    assert "deploy/prod.yml" in refs
    assert "memory.md" in refs


def test_secret_detection_and_redaction() -> None:
    text = "OPENAI_API_KEY=sk-proj-abcdefghijklmnop1234"
    assert secret_matches(text)
    assert sensitivity_for(text) == "secret"
    assert "sk-proj" not in redact_text(text)
    assert "[REDACTED]" in redact_text(text)


def test_placeholders_are_not_secrets() -> None:
    assert sensitivity_for("API_KEY=<your-key>") == "normal"
    assert sensitivity_for("password: changeme") == "normal"


def test_private_key_body_and_bearer_tokens_are_redacted() -> None:
    key = (
        "-----BEGIN PRIVATE KEY-----\n"
        "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n"
        "-----END PRIVATE KEY-----"
    )
    assert "MIIEvQ" not in redact_text(key)
    assert "[REDACTED]" in redact_text(key)
    assert "abcdefghijklmnop1234" not in redact_text("Authorization: Bearer abcdefghijklmnop1234")


def test_stable_id_changes_with_source() -> None:
    first = stable_memory_id("markdown", "a.md", "Use SQLite")
    second = stable_memory_id("markdown", "b.md", "Use SQLite")
    assert first != second
    assert first == stable_memory_id("markdown", "a.md", "Use SQLite")
    assert stable_memory_id("markdown", "a.md", "Use SQLite", explicit="ms_custom") == "ms_custom"
